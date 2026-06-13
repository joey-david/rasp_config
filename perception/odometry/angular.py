"""Yaw-rate estimate from global horizontal image shift."""

import argparse
import csv
import math

import cv2
import numpy as np

try:
    from .source import DriveCommand, frame_path, gray_frames, run_dir
except ImportError:  # pragma: no cover - direct script execution
    from source import DriveCommand, frame_path, gray_frames, run_dir


class AngularSpeedEstimator:
    def __init__(self, fx_px=None, fov_deg=None, roi=(0.25, 0.75)):
        self.fx_px = fx_px or (80 / math.tan(math.radians(fov_deg or 62) / 2))
        self.roi = roi
        self.prev = None
        self.prev_t = None

    def update(self, gray, t):
        h = gray.shape[0]
        band = gray[int(h * self.roi[0]) : int(h * self.roi[1])].astype(np.float32)
        if self.prev is None:
            self.prev, self.prev_t = band, t
            return None

        (dx, _), score = cv2.phaseCorrelate(self.prev, band)
        dt = max(1e-6, t - self.prev_t)
        self.prev, self.prev_t = band, t

        return {
            "rad_s": (dx / self.fx_px) / dt,
            "dx": dx,
            "dt": dt,
            "score": score,
        }


def speed_name(x):
    return f"{abs(float(x)):g}".replace(".", "p")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--camera", help="OpenCV camera index or MJPEG URL")
    p.add_argument("--frames-dir", help="directory of calibration/test images")
    p.add_argument("--fps", type=float, default=30)
    p.add_argument("--seconds", type=float)
    p.add_argument("--out-dir")
    p.add_argument("--no-save-frames", action="store_true")
    p.add_argument("--drive-linear", type=float)
    p.add_argument("--drive-angular", type=float)
    p.add_argument("--countdown", type=float, default=3)
    p.add_argument("--from-csv", help="samples.csv from a recorded run")
    p.add_argument("--start-frame", type=int)
    p.add_argument("--end-frame", type=int)
    p.add_argument("--turns", type=float, default=1.0)
    p.add_argument("--fx-px", type=float, help="calibrated horizontal focal length")
    p.add_argument("--fov-deg", type=float, default=62)
    args = p.parse_args()

    if args.from_csv:
        with open(args.from_csv, newline="") as f:
            rows = list(csv.DictReader(f))

        if args.start_frame is None or args.end_frame is None:
            raise SystemExit("--start-frame and --end-frame are required")

        dx = sum(
            float(r["dx"])
            for r in rows
            if args.start_frame < int(r["frame"]) <= args.end_frame
        )
        fx = abs(dx) / (2 * math.pi * abs(args.turns))
        print(
            f"frames={args.start_frame}->{args.end_frame} dx_sum={dx:.2f} fx_px={fx:.2f}"
        )
        return

    if args.seconds is None:
        angular = abs(args.drive_angular or 0)
        args.seconds = max(1.0, 25.0 - angular / 5.0)

    if args.out_dir is None and args.drive_angular is not None:
        args.out_dir = f"calibrations/odometry/angular_{speed_name(args.drive_angular)}"

    est = AngularSpeedEstimator(args.fx_px, args.fov_deg)
    out = run_dir("angular", args.out_dir)
    csv_path = out / "samples.csv"
    total_dx = 0.0
    limit = int(args.seconds * args.fps) if args.seconds else 0

    print(
        f"recording angular odometry to {out} at {args.fps:g} fps for {args.seconds:g}s"
    )
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
                f, ["frame", "t", "dt", "dx", "dx_sum", "rad_s", "score"]
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
                    "dx": 0,
                    "dx_sum": total_dx,
                    "rad_s": "",
                    "score": "",
                }

                out_est = est.update(gray, t)
                if out_est:
                    total_dx += out_est["dx"]
                    row |= {
                        "dt": f"{out_est['dt']:.6f}",
                        "dx": f"{out_est['dx']:.6f}",
                        "dx_sum": f"{total_dx:.6f}",
                        "rad_s": f"{out_est['rad_s']:.6f}",
                        "score": f"{out_est['score']:.6f}",
                    }

                writer.writerow(row)

                if frame % int(max(1, args.fps)) == 0:
                    print(f"frame={frame} dx_sum={total_dx:.1f}")

                if limit and frame >= limit:
                    break

    finally:
        drive.stop()

    print(f"saved {csv_path}")


if __name__ == "__main__":
    main()
