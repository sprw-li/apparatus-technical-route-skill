# Process flow and technical route — SYNTHETIC EXAMPLE - NOT AN OFFICIAL CASE

Invented process description for this example. Not a real process and not a measurement.

## Ordered steps of one campaign

1. Feed preparation — a 20.0 mg/L methylene blue stock is diluted to 10.0 mg/L in the feed reservoir A1.
2. Feed pumping — the peristaltic pump A2 moves the diluted feed at 2.4 mL/min into the reactor line.
3. Air sparging and mixing — the mass-flow controller A5 adds air at 0.8 L/min and the static mixer A3 blends it into the feed.
4. Photocatalytic oxidation — the annular reactor A4 irradiates the packed bed with 365 nm UV-LED light; the hydraulic residence time is 8.0 min.
5. Inline monitoring — the sensor A6 logs absorbance at 254 nm every 30 s while the jacket A7 holds the reactor at 25.0 °C.
6. Membrane separation — two parallel membrane modules split the reactor outlet into permeate and a catalyst-rich retentate.
7. Permeate collection — the clarified permeate fills the product reservoir A9.
8. Concentrate discharge — at the end of the campaign the retained concentrate is drained to the waste bottle A10.

## Parallel and recycle streams

- Modules M1 and M2 are two parallel membrane modules fed from the same reactor-outlet line; either can be isolated for cleaning without stopping the run.
- The retentate from M1 and from M2 is returned to the feed reservoir A1, which is the internal recycle loop of the rig.
- The two retentate lines merge into a single concentrate line that is drained to A10 only at the end of a campaign.

## Technology route

- Phase-1 catalyst screening — goal: rank three catalyst loadings by conversion; methods: batch screens and BET surface-area measurement; inputs: three TiO2 powder batches; outputs: a shortlist; depends_on: none.
- Phase-2 process optimisation — goal: maximise conversion per unit of UV energy; methods: a factorial design over flow rate and air flow; inputs: the shortlisted catalyst; outputs: an operating window; depends_on: Phase-1.
- Phase-3 validation — goal: demonstrate 72 h of continuous stability; methods: a continuous run with daily sampling; inputs: the operating window; outputs: a stability report; depends_on: Phase-2.
- Phase-4 scale-up assessment — goal: estimate the energy demand per order of magnitude; methods: dimensional analysis against the measured energy demand; inputs: the stability report; outputs: a scale-up plan; depends_on: Phase-3.
