// Isolated entry for the toolchain smoke test.
import React from "react";
import { Composition, registerRoot } from "remotion";
import { Smoke } from "../Smoke";

registerRoot(() => <Composition id="Smoke" component={Smoke} width={1920} height={1080} fps={60} durationInFrames={90} />);
