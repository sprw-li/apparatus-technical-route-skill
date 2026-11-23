# Apparatus list — SYNTHETIC EXAMPLE - NOT AN OFFICIAL CASE

Invented apparatus for this example. It is internally consistent, but it is not a real rig
and nothing here may be cited as a measurement.

## Components

- A1 Feed reservoir (part: tank) — borosilicate glass vessel holding 5.0 L of diluted dye feed; its outlet line runs to the peristaltic pump A2.
- A2 Peristaltic pump (part: pump) — delivers the feed at 2.4 mL/min; the calibrated range is 0.5 to 10.0 mL/min.
- A3 Static mixer (part: mixer) — inline helical mixer that blends the feed with the sparged air stream before the reactor.
- A4 Annular UV-LED reactor (part: reactor) — 250 mm borosilicate annulus packed with 1.2 g/L of immobilised TiO2; nominal hydraulic residence time 8.0 min at 2.4 mL/min.
- A5 Air mass-flow controller (part: instrument) — meters the sparge gas at 0.8 L/min and holds the dissolved-oxygen set point.
- A6 Inline UV-Vis sensor (part: sensor) — measures absorbance at 254 nm on the reactor outlet line; usable range 0.00 to 3.00 AU.
- A7 Thermostatic jacket (part: heater) — recirculates water at 25.0 °C around the reactor wall.
- A8 Ceramic membrane separator (part: separator) — 0.2 micrometre membrane that retains catalyst fines.
- A9 Product reservoir (part: reservoir) — collects the clarified permeate; 2.0 L working volume.
- A10 Waste bottle (part: waste) — receives the retained concentrate at the end of a campaign.
- A11 Sampling port (part: sample) — septum port on the reactor outlet line for grab samples.
- A12 UV-LED driver (part: instrument) — drives the 365 nm LED array inside A4.
- A13 Permeate pump (part: pump) — draws permeate through the membrane at 1.0 mL/min.

## Ports and connections

- The reactor A4 carries four ports: inlet (bottom, from A3), outlet (top, to A6), gas_in (bottom, from A5) and uv_in (side, from A12).
- The feed reservoir A1 carries two ports: outlet (bottom, to A2) and return (top, from the membrane retentate).
- The membrane A8 carries two ports: feed (side, from A13) and retentate (bottom, back to A1).
- A6 is wired to A2 as a control loop: when the logged absorbance rises above its set point the pump speed is reduced.
- The retentate line from A8 back to A1 forms the internal recycle loop of the rig.
