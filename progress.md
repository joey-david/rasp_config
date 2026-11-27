# Building the robot

### Pre May 15th, 2026

Struggled to set up bookwork via usb since I didn't have a microsd. At first it wouldn't even boot and it would display a boot image error, via fourfold fast flashing of the green ACT light. I finally succeeded in finding a working USB, after which I modified the bookworm image with a launch script that automatically enabled SSH and connected to my home Wi-Fi so that I could set it up without plugging in a keyboard or display, over ssh.

!

### May 15th, 2026

Received the camera and microsd. Microsd doesn't work, it's counterfeit :/. Camera does work though - I set up a web ui app to see what it sees easily over ssh, including image inversion and fisheye correction parameters.

- ReSpeaker 2-mic HAT: the stock WM8960 path failed on reset; switching to the board-specific `seeed-2mic-voicecard` overlay plus a kernel-matched WM8960 module exposed ALSA capture on `card 1`, and the camera UI now records synced audio+video `.mkv` files.

### May 16-17th

Set up connections with jumper cables and breadboard, and even motors by threading the jumpers correctly. Test didn't work - I couldn't solder the motor's bridge's pins to its plates as I had no soldering iron. It looks like a massive mess.

### May 18th

Soldered bridge pins and plates. Got B backward, A forward, A backward, but B forward isn't working... That's because I shorted power and a B-in while soldering the pins, it took out the RP1 pins of my pi. Changing to another set of GPIO fixed it and the motors spin. Now to custom-build by sticking, mounting the whole thing together, cutting the right custom-length and custom arranged cables between driver, breakout, pi and motors, find emplacements.
Also have got to find a good battery to power it all.
Got a wheel spinning worse than the other, (stops spinning faster, as if more friction).

### May 19th

Got a short-ish microusb cable for onboard feeding of the pi via portable battery.
Got rid of the breadboard, starting manual stripping of male-female cables and reassembly into appropriate size female-female to join the pi to the driver/bridge, 5/9

### May 20th

completed pi pinnings, linked driver to motors and made breakout connections. Mounted it together, didn't work. Possible short between gnd and vcc on the driver.

### May 28th

Moved to a replacement Raspberry Pi after the old one was fried during the earlier wiring/power mistakes. Remapped the TB6612 motor controls to the available physical pins 29-40 and disabled the ReSpeaker/I2S overlay to free pins 35/38/40. Added smoother `lgpio` 1 kHz PWM motor testers. After chasing GPIO and driver hypotheses, the final blocker was just a dead cable; replacing it made the motors work.
The prototype to the prototype runs, using tape and unstable elts. Uneven wheels power makes it turn though. Have issues where one wheel stops being powered and the other starts going full steam if I push the low pwm mode too hard.

### May 30th

Diagnosed: bad motor with exagerated friction. Delayed parts delivery. Starting the software engineering, started the video project. Created level 0 especially - tank, pwm management, web interface redoing, etc. Rethought split of compute: only level 0 will run on pi, advanced visual detection will be on laptop.

## June 1st

Implemented motors and motion from scratch, with smart release of gpio for concurrent exec and web watching, etc.
Started implementing lock-on - need to do a bunch of optimisations with the 3hz-30hz system, as the pi saturates and can't keep up : only keep track of important objects (in this case person), downsize image from the get-go, etc.
Switched to kalman filter, sort algorithm for bbox retention, PD for speed tracking and avoiding oscillations.

## June 11th

Getting lock-on in a close-to-reliable state. Need to drastically simplify it, some cumulative offset bonus (with strong decrease when in tolerable center + some occilation counteracting should be enough, maybe even more reliable.)

## June 12th

Semantic matcher for closest COCO target (will be useful for LLM parsing/matching of targets). Tested on web interface with lock_on.Lots of refactorization for later ease of expansion. Changed lock_on to be general.

## June 13th

Added odometry folder for hyper-low-latency on-device visual speed estimation.
Important: established that the operative range for turning is 30-45: under 30 has too much friction, above 50 can't capture angular speed meaninfully - only use for _EMOTES_. Added emotes. Emergent find behavior in find_odometry.

## July 15th

Completed the first end-to-end autonomy stack. Level 0 now continuously checks a fresh 320x240 grayscale support-surface view and fails closed on stale or uncalibrated camera data. Level 1 remains the only motor owner. Level 2 now has stop-and-look `find`, `go_to`, `push`, `push_to`, `follow`, and shared 35-45 turn tuning. Detections carry current age, quality, normalized geometry, and explicitly non-metric relative depth; command odometry feeds a rough relative landmark map.

Level 3 is a bounded sense-plan-act controller. It sends one current frame plus the compact scene/map to a remote VLM shim, validates one action from a fixed skill schema, and never exposes raw motor commands. Autonomous contact is disabled by default, living targets are locally protected, and a stop received during remote inference discards the eventual planner response. Coordinated runs print level 0 through level 3 activation, perception/map state, actual movement pulses, safety transitions/vetoes, and planner request/action/result lines.

Validation: 24 local unit/integration tests pass, including duplicate-frame edge confirmation, stale-camera fail-closed behavior, level-1 command mapping, both `find` precheck paths, route dispatch, planner validation, and the stop-during-inference race. The mock FastAPI server passed authenticated and image-bearing HTTP round trips. Warm Mac MPS YOLO checks on the standard bus image took about 35 ms at 640, 74 ms at 1280, and 328 ms at 2592; semantic query results are now cached and concurrent model entry is serialized.

Before the robot went offline, the deployed service restarted successfully with live grayscale, fresh enriched YOLO detections, a populated relative map, and edge safety calibrated and clear. The final logging/tuning/race fixes above still need redeployment. Physical table-edge approach, forward `go_to`, and contact/push tests remain intentionally unverified while the robot is unavailable.

## July 25th

Audited the offline stack against the full robot path. Edge danger now stays latched until four clear frames and cannot learn from those recovery frames. `find` stays within the measured 35-45 turn band and resumes scanning if centering loses the target. `push_to` now checks the source and destination after each short push, stops on lack of progress, and rejects living destinations. The planner detects objects in the exact JPEG sent to the VLM. The map uses the robot pose from that frame's capture time, and it now receives every real motor change, including watchdog stops.

Fixed control races: the web server claims one skill before label resolution starts, autonomy remains busy until an in-flight plan call exits, and manual motion cannot start over a running skill. The configured motor power now caps each wheel. Camera crop or flip changes reset edge learning. State polling uses one guarded path, so a lost API prints one error instead of throwing on every poll. Removed the saved Pi sudo password from the deploy script.

Validation: 38 unit and integration tests pass. The real Mac MPS detector server passed health, exact-label, and JPEG POST tests. On a saved 4000x3000 workbench frame, full-sensor input with `imgsz=1920` found the potted plant at 0.80; `2592` fell to 0.281, so high-detail inference now defaults to 1920 while capture stays 2592x1944. The authenticated mock VLM server and `RemotePlanner` passed an image-bearing HTTP call and rejected a missing token with 401. Chrome checks passed at desktop and 390x844, including the settings drawer. The Pi is still offline, so this revision has not been deployed and no new wheel, edge, approach, or push result has been claimed.
