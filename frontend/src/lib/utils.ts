import typeRamp from "@plivo/tokens/type.json";
import { createCn } from "cn/config";

/** The type ramp of @plivo/tokens. Without this list cn() reads `text-s-400` as a text color, and
 * a later color class in the same call drops it. */
const TYPE_SCALE = Object.keys(typeRamp);

export const cn = createCn({ extend: { classGroups: { "font-size": [{ text: TYPE_SCALE }] } } });
