import { describe, it, expect, beforeEach } from "vitest";
import { replayKeyIgnored } from "./keyTarget";

beforeEach(() => {
  document.body.innerHTML = "";
});

describe("replayKeyIgnored", () => {
  it("ignores inputs, comboboxes and listbox options", () => {
    document.body.innerHTML =
      '<input id="i"/><div role="combobox"><span id="c"></span></div><ul role="listbox"><li role="option" id="o"></li></ul>';
    // listbox present is not a popover; check each target explicitly
    expect(replayKeyIgnored(document.getElementById("i"))).toBe(true);
    expect(replayKeyIgnored(document.getElementById("c"))).toBe(true);
    expect(replayKeyIgnored(document.getElementById("o"))).toBe(true);
  });
  it("does not ignore a plain button or tab", () => {
    document.body.innerHTML = '<button id="b"></button><div role="tab" id="t"></div>';
    expect(replayKeyIgnored(document.getElementById("b"))).toBe(false);
    expect(replayKeyIgnored(document.getElementById("t"))).toBe(false);
  });
  it("ignores everything while a MUI popover is open", () => {
    document.body.innerHTML = '<div class="MuiPopover-root"></div><button id="b"></button>';
    expect(replayKeyIgnored(document.getElementById("b"))).toBe(true);
  });
});
