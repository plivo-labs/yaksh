import { createCn } from "cn/config";

/** The type scale utilities in index.css. Without this list cn() reads `text-s-400` as a text
 * color, and a later color class in the same call drops it. */
const TYPE_SCALE = [
  "h3-500",
  "h4-500",
  "p-400",
  "p-500",
  "s-400",
  "s-500",
  "xs-400",
  "xs-500",
  "label",
];

export const cn = createCn({ extend: { classGroups: { "font-size": [{ text: TYPE_SCALE }] } } });
