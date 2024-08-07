# JPTH-13MPoE Satellite Tracker

This project repurposes a JPTH-13MPoE surveillance camera mount for good, by turning it into an Az-El antenna rotator for talking to satellites. It translates between the rotctld protocol used by amateur radio tools like GPredict and the JPTH-13MPoE's web interface.

To use:

1. Adjust the limit switches on your JPTH-13MPoE and calibrate it. Beware of the pan angle sensor's wraparound point: it needs to be outside the pan limits!
2. Edit the script to have your JPTH-13MPoE's web interface URL in it. Also fill in the angle between pan 0 and due north.
3. Run the script.
4. In GPredict, go to "Preferences", then "Interfaces", and then the "Rotators" tab. Add a new rotator at 127.0.0.1 port 4533. Use the 0 -> 180 -> 360 "Azimuth Type".
5. In GPredict's "Antenna Control", "Engage" the rotator and then "Track" a satellite!

Note that the script can only take one (local) connection at a time. Also the tracking isn't very good yet; it lags behind the satellite by about a degree because I haven't written any PID control.
