/** localStorage that fails quietly: where the browser blocks it, choices last for this page only. */
export const storage: Pick<Storage, "getItem" | "setItem"> = {
  getItem: (key) => {
    try {
      return localStorage.getItem(key);
    } catch {
      return null;
    }
  },
  setItem: (key, value) => {
    try {
      localStorage.setItem(key, value);
    } catch {
      // storage blocked
    }
  },
};
