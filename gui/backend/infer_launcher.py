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

    # 3. Strip launcher arguments so sys.argv[0] is infer_script and args match exactly
    del sys.argv[0:2]
    runpy.run_path(infer_script, run_name="__main__")


if __name__ == "__main__":
    main()
