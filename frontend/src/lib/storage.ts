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

/** sessionStorage that fails quietly, for a draft that should outlive a reload in this tab only. */
export const sessionDraft: Pick<Storage, "getItem" | "setItem" | "removeItem"> = {
  getItem: (key) => {
    try {
      return sessionStorage.getItem(key);
    } catch {
      return null;
    }
  },
  setItem: (key, value) => {
    try {
      sessionStorage.setItem(key, value);
    } catch {
      // storage blocked
    }
  },
  removeItem: (key) => {
    try {
      sessionStorage.removeItem(key);
    } catch {
      // storage blocked
    }
  },
};
