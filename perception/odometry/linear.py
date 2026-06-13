"""Forward-speed proxy from lower-image floor flow."""

import argparse
import csv

import cv2
import numpy as np

try:
    from .source import DriveCommand, frame_path, gray_frames, run_dir
except ImportError:  # pragma: no cover - direct script execution
    from source import DriveCommand, frame_path, gray_frames, run_dir


class LinearSpeedEstimator:
    def __init__(self, meters_per_pixel=0.0, roi=(0.55, 0.95)):
        self.meters_per_pixel = meters_per_pixel
        self.roi = roi
        self.prev = None
        self.prev_t = None

    def update(self, gray, t):
        h = gray.shape[0]
        floor = gray[int(h * self.roi[0]) : int(h * self.roi[1])].astype(np.float32)
        if self.prev is None:
            self.prev, self.prev_t = floor, t
            return None
        (_, dy), score = cv2.phaseCorrelate(self.prev, floor)
        dt = max(1e-6, t - self.prev_t)
        self.prev, self.prev_t = floor, t
        return {
            "m_s": (dy * self.meters_per_pixel) / dt,
            "dy": dy,
            "dt": dt,
            "score": score,
        }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--camera", help="OpenCV camera index or MJPEG URL")
    p.add_argument("--frames-dir", help="directory of calibration/test images")
    p.add_argument("--fps", type=float, default=30)
    p.add_argument("--seconds", type=float, default=20)
    p.add_argument("--out-dir")
    p.add_argument("--no-save-frames", action="store_true")
    p.add_argument("--drive-linear", type=float)
    p.add_argument("--drive-angular", type=float)
    p.add_argument("--countdown", type=float, default=3)
    p.add_argument("--from-csv", help="samples.csv from a recorded run")
    p.add_argument("--start-frame", type=int)
    p.add_argument("--end-frame", type=int)
    p.add_argument("--meters-per-pixel", type=float, default=0.0)
    p.add_argument("--meters", type=float, help="known forward travel distance")
    args = p.parse_args()

    if args.from_csv:
        with open(args.from_csv, newline="") as f:
            rows = list(csv.DictReader(f))
        if args.start_frame is None or args.end_frame is None or args.meters is None:
            raise SystemExit("--start-frame, --end-frame, and --meters are required")
        dy = sum(
            float(r["dy"])
            for r in rows
            if args.start_frame < int(r["frame"]) <= args.end_frame
        )
        k = args.meters / abs(dy) if dy else 0.0
        print(
            f"frames={args.start_frame}->{args.end_frame} dy_sum={dy:.2f} "
            f"meters_per_pixel={k:.6f}"
        )
        return

    est = LinearSpeedEstimator(args.meters_per_pixel)
    out = run_dir("linear", args.out_dir)
    csv_path = out / "samples.csv"
    total_dy = 0.0
    limit = int(args.seconds * args.fps) if args.seconds else 0
    print(f"recording linear odometry to {out} at {args.fps:g} fps")
    print("mark your start/end frame later, then run with --from-csv samples.csv")
    drive = DriveCommand(args.drive_linear, args.drive_angular, args.countdown)
    try:
        source = gray_frames(args.camera, args.frames_dir, fps=args.fps)
        try:
            first = next(source)
        except StopIteration:
            raise SystemExit("camera/source ended before any frame was recorded")
        print("camera ready", flush=True)
        drive.start()
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(
                f, ["frame", "t", "dt", "dy", "dy_sum", "m_s", "score"]
            )
            writer.writeheader()
            frame = 0
            est.prev = None
            est.prev_t = None
            for gray, t in source:
                drive.refresh()
                frame += 1
                if not args.no_save_frames:
                    cv2.imwrite(str(frame_path(out, frame)), gray)
                row = {
                    "frame": frame,
                    "t": f"{t:.6f}",
                    "dt": "",
                    "dy": 0,
                    "dy_sum": total_dy,
                    "m_s": "",
                    "score": "",
                }
                out_est = est.update(gray, t)
                if out_est:
                    total_dy += out_est["dy"]
                    row |= {
                        "dt": f"{out_est['dt']:.6f}",
                        "dy": f"{out_est['dy']:.6f}",
                        "dy_sum": f"{total_dy:.6f}",
                        "m_s": f"{out_est['m_s']:.6f}",
                        "score": f"{out_est['score']:.6f}",
                    }
                writer.writerow(row)
                if frame % int(max(1, args.fps)) == 0:
                    print(f"frame={frame} dy_sum={total_dy:.1f}")
                if limit and frame >= limit:
                    break
    finally:
        drive.stop()
    print(f"saved {csv_path}")


if __name__ == "__main__":
    main()
