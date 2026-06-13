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
