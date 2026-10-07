// Render settings for the Paladex launch ad. See https://www.remotion.dev/docs/config
import { Config } from "@remotion/cli/config";

// GPU WebGL on Windows (three.js scenes); "swangle" (software) on GPU-less Linux containers.
const WIN = process.platform === "win32";
Config.setChromiumOpenGlRenderer(WIN ? "angle" : "swangle");
if (!WIN) Config.setBrowserExecutable(process.env.REMOTION_BROWSER ?? "/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell");
Config.setVideoImageFormat("jpeg");
Config.setJpegQuality(95);
Config.setCodec("h264");
Config.setCrf(16);
Config.setPixelFormat("yuv420p");
Config.setX264Preset("slow");
Config.setAudioBitrate("320k");
Config.setDelayRenderTimeoutInMilliseconds(120000);
