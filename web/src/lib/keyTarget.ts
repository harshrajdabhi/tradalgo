const SELECTOR =
  'input, textarea, select, [contenteditable="true"], [role="combobox"], [role="listbox"], [role="option"], [role="menu"], [role="menuitem"]';

/** True when a replay hotkey should be left to the focused control. */
export function replayKeyIgnored(target: EventTarget | null, doc: Document = document): boolean {
  const el = target as HTMLElement | null;
  if (el && typeof el.closest === "function" && el.closest(SELECTOR)) return true;
  // An open MUI menu/popover owns the keyboard.
  return !!doc.querySelector('[role="presentation"] [role="listbox"], .MuiPopover-root, .MuiMenu-root');
}
