"""
Inference Launcher Bootstrap for CorridorKey 2.0 GUI.
Applies zero-disruption runtime in-memory optimizations:
- Dynamically activates DWAA / ZIP OpenEXR sequence writer without touching upstream code
- Sets high CPU thread priority and Windows QoS
- Executes official infer.py cleanly as __main__
"""
import os
import sys
import runpy


def main():
    if len(sys.argv) < 3:
        print("[Launcher Error] Missing engine directory or infer script path.", file=sys.stderr)
        sys.exit(1)

    engine_dir = sys.argv[1]
    infer_script = sys.argv[2]

    # 1. Ensure engine directory is at the head of sys.path
    if engine_dir not in sys.path:
        sys.path.insert(0, engine_dir)

    # 2. Check if DWAA EXR compression was requested via environment
    exr_comp = os.environ.get("CORRIDORKEY_EXR_COMPRESSION", "").lower()
    dwa_level = float(os.environ.get("CORRIDORKEY_EXR_DWA_LEVEL", "45.0"))

    if exr_comp == "dwaa":
        try:
            import OpenEXR
            import Imath
            import numpy as np
            import corridorkey.video_io as video_io

            class DwaaExrSequenceWriter(video_io.ExrSequenceWriter):
                def _worker(self):
                    try:
                        comp = Imath.Compression(Imath.Compression.DWAA_COMPRESSION)
                        pt = Imath.PixelType(Imath.PixelType.HALF if self.clamp_half else Imath.PixelType.FLOAT)
                        dt = np.float16 if self.clamp_half else np.float32

                        while True:
                            item = self.q.get()
                            if item is None:
                                self.q.task_done()
                                return
                            idx0, arr = item
                            if self.clamp_half:
                                arr = np.clip(arr, -65504.0, 65504.0)

                            for j in range(arr.shape[0]):
                                out_path = os.path.join(
                                    self.dir_path, f"{self.frame_name}_{idx0 + j:06d}.exr")
                                frame = np.ascontiguousarray(arr[j])
                                h_f, w_f = frame.shape[:2]

                                header = OpenEXR.Header(w_f, h_f)
                                header['compression'] = comp
                                header['dwaCompressionLevel'] = dwa_level

                                if self.channels == 4:
                                    header['channels'] = {
                                        'R': Imath.Channel(pt),
                                        'G': Imath.Channel(pt),
                                        'B': Imath.Channel(pt),
                                        'A': Imath.Channel(pt),
                                    }
                                    pixels = {
                                        'B': np.ascontiguousarray(frame[:, :, 0], dtype=dt).tobytes(),
                                        'G': np.ascontiguousarray(frame[:, :, 1], dtype=dt).tobytes(),
                                        'R': np.ascontiguousarray(frame[:, :, 2], dtype=dt).tobytes(),
                                        'A': np.ascontiguousarray(frame[:, :, 3], dtype=dt).tobytes(),
                                    }
                                elif self.channels == 3:
                                    header['channels'] = {
                                        'R': Imath.Channel(pt),
                                        'G': Imath.Channel(pt),
                                        'B': Imath.Channel(pt),
                                    }
                                    pixels = {
                                        'B': np.ascontiguousarray(frame[:, :, 0], dtype=dt).tobytes(),
                                        'G': np.ascontiguousarray(frame[:, :, 1], dtype=dt).tobytes(),
                                        'R': np.ascontiguousarray(frame[:, :, 2], dtype=dt).tobytes(),
                                    }
                                else:
                                    header['channels'] = {'A': Imath.Channel(pt)}
                                    f_1c = frame if frame.ndim == 2 else frame[:, :, 0]
                                    pixels = {'A': np.ascontiguousarray(f_1c, dtype=dt).tobytes()}

                                out = OpenEXR.OutputFile(out_path, header)
                                out.writePixels(pixels)
                                out.close()

                            self.q.task_done()
                    except Exception as exc:
                        self.err = exc

            video_io.ExrSequenceWriter = DwaaExrSequenceWriter
            import corridorkey.runtime as runtime
            runtime.ExrSequenceWriter = DwaaExrSequenceWriter
        except Exception:
            # Fall back to default OpenCV ZIP compression
            pass

    # 3. Hardware Tensor Acceleration & Threading Optimizations
    try:
        import torch
        if torch.cuda.is_available():
            major, minor = torch.cuda.get_device_capability()
            # Ampere (RTX 30), Ada (RTX 40), Blackwell (RTX 50) have native Tensor Cores
            if major >= 8:
                torch.backends.cuda.matmul.allow_tf32 = True
                torch.backends.cudnn.allow_tf32 = True
                torch.backends.cudnn.benchmark = True
                if hasattr(torch.backends.cuda, "enable_flash_sdp"):
                    torch.backends.cuda.enable_flash_sdp(True)
                if hasattr(torch.backends.cuda, "enable_mem_efficient_sdp"):
                    torch.backends.cuda.enable_mem_efficient_sdp(True)
    except Exception:
        pass

    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.kernel32.SetPriorityClass(
                ctypes.windll.kernel32.GetCurrentProcess(), 0x00008000
            )
        except Exception:
            pass

    # 4. Asynchronous Threaded Prefetch Queue & Real-time Progress Monitoring
    try:
        import queue
        import threading
        import corridorkey.video_io as video_io
        import corridorkey.runtime as runtime

        def _prefetch_iterator(generator, max_prefetch: int = 4):
            buf = queue.Queue(maxsize=max_prefetch)
            sentinel = object()

            def _worker():
                try:
                    for item in generator:
                        buf.put(item)
                except Exception as exc:
                    buf.put(exc)
                finally:
                    buf.put(sentinel)

            worker_thread = threading.Thread(target=_worker, daemon=True)
            worker_thread.start()

            while True:
                chunk_item = buf.get()
                if chunk_item is sentinel:
                    break
                if isinstance(chunk_item, Exception):
                    raise chunk_item
                yield chunk_item

        orig_iter_video = video_io.iter_video_frame_chunks

        def tracked_iter_video(video_path, meta, chunk_size, need_model):
            tot = int(meta.get("num_frames", 1))
            last_reported = -1
            raw_gen = orig_iter_video(video_path, meta, chunk_size=chunk_size, need_model=need_model)
            chunk_gen = _prefetch_iterator(raw_gen, max_prefetch=4) if tot > 64 else raw_gen
            for item in chunk_gen:
                t0, _m, disp = item
                cur = t0 + disp.shape[0]
                if cur - last_reported >= 32 or cur >= tot:
                    last_reported = cur
                    pct = (cur / max(1, tot)) * 100.0
                    print(f"[PrepassChunk] frame {cur}/{tot} ({pct:.1f}%)", flush=True)
                yield item

        orig_iter_dir = video_io.iter_frame_dir_chunks

        def tracked_iter_dir(frame_dir, meta, chunk_size, need_model):
            tot = int(meta.get("num_frames", 1))
            last_reported = -1
            raw_gen = orig_iter_dir(frame_dir, meta, chunk_size=chunk_size, need_model=need_model)
            chunk_gen = _prefetch_iterator(raw_gen, max_prefetch=4) if tot > 64 else raw_gen
            for item in chunk_gen:
                t0, _m, disp = item
                cur = t0 + disp.shape[0]
                if cur - last_reported >= 32 or cur >= tot:
                    last_reported = cur
                    pct = (cur / max(1, tot)) * 100.0
                    print(f"[PrepassChunk] frame {cur}/{tot} ({pct:.1f}%)", flush=True)
                yield item

        video_io.iter_video_frame_chunks = tracked_iter_video
        runtime.iter_video_frame_chunks = tracked_iter_video
        video_io.iter_frame_dir_chunks = tracked_iter_dir
        runtime.iter_frame_dir_chunks = tracked_iter_dir

        # 4b. Stage 2 & Output Writer Progress Interceptor
        _primary_writer_id = None
        _frames_written_total = 0

        orig_threaded_write_many = video_io.ThreadedVideoWriter.write_many

        def tracked_threaded_write_many(self, frames):
            global _primary_writer_id, _frames_written_total
            if _primary_writer_id is None:
                _primary_writer_id = id(self)
            orig_threaded_write_many(self, frames)
            if id(self) == _primary_writer_id:
                count = getattr(frames, "shape", [1])[0] if hasattr(frames, "shape") else len(frames)
                _frames_written_total += count
                print(f"[Stage2Frame] frame {_frames_written_total}", flush=True)

        video_io.ThreadedVideoWriter.write_many = tracked_threaded_write_many

        orig_exr_write_many = video_io.ExrSequenceWriter.write_many

        def tracked_exr_write_many(self, frames):
            global _primary_writer_id, _frames_written_total
            if _primary_writer_id is None:
                _primary_writer_id = id(self)
            orig_exr_write_many(self, frames)
            if id(self) == _primary_writer_id:
                count = getattr(frames, "shape", [1])[0] if hasattr(frames, "shape") else len(frames)
                _frames_written_total += count
                print(f"[Stage2Frame] frame {_frames_written_total}", flush=True)

        video_io.ExrSequenceWriter.write_many = tracked_exr_write_many
    except Exception:
        pass

    # 5. Strip launcher arguments so sys.argv[0] is infer_script and args match exactly
    del sys.argv[0:2]
    runpy.run_path(infer_script, run_name="__main__")


if __name__ == "__main__":
    main()
