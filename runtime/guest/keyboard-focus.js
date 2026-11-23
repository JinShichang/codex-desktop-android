(() => {
  const key = '__codexImeV7';
  if (globalThis[key]) {
    globalThis[key].resync();
    return 'already-installed';
  }
  // Subsequent versions can remove every listener before installing a new hook.
  // V4 did not expose disposal and needs one document reload when upgrading.
  globalThis.__codexImeHook?.dispose();
  const controller = new AbortController();
  const signal = controller.signal;
  const sequenceKey = '__codexImeSequence';
  globalThis[sequenceKey] ??= 0;
  let disposed = false;
  let pending;
  const textTypes = new Set(['text', 'search', 'email', 'url', 'tel', 'password', 'number']);
  function parent(node) {
    return node.parentElement || node.getRootNode()?.host;
  }
  function editable(node) {
    if (!(node instanceof Element)) return false;
    // Roles alone do not make a node editable. Respect restrictions across
    // shadow boundaries as well as native disabled fieldsets.
    for (let ancestor = node; ancestor instanceof Element; ancestor = parent(ancestor)) {
      if (ancestor.hasAttribute('inert') || ancestor.getAttribute('aria-disabled') === 'true' ||
          ancestor.getAttribute('aria-readonly') === 'true') return false;
    }
    if (node.matches('input')) return !node.matches(':disabled') && !node.readOnly && textTypes.has(node.type);
    if (node.matches('textarea')) return !node.matches(':disabled') && !node.readOnly;
    return node.isContentEditable;
  }
  function active() {
    let node = document.activeElement;
    while (node?.shadowRoot?.activeElement) node = node.shadowRoot.activeElement;
    return node;
  }
  function terminalInput(node) {
    const terminal = node?.closest('.xterm');
    const input = terminal?.querySelector('textarea.xterm-helper-textarea');
    return input && editable(input) && !node.closest('.xterm-scrollbar, .scrollbar') ? input : null;
  }
  function report(visible, reason) {
    if (disposed) return;
    // Focusing the prompt after Send is application behavior, not a request to
    // type again. Opening is reserved for a trusted pointer event below.
    if (visible && reason !== 'pointer') return;
    // A trusted pointerdown may precede document focus when entering an iframe.
    // Its user gesture is sufficient; retained background focus never gets here.
    if (visible && document.visibilityState !== 'visible') return;
    // No values, labels, field contents or keystrokes are transmitted.
    globalThis.__codexImeSignal(JSON.stringify({visible, reason, sequence: ++globalThis[sequenceKey]}));
  }
  function reportCurrent(reason) {
    const node = active();
    // The child document owns its focus signal. A parent's delayed focusout
    // must not race the child's focusin and dismiss its keyboard.
    if (node?.matches('iframe,frame')) return;
    // Preserve a keyboard that is already open during field handover. Never
    // infer that retained/programmatic focus should reopen a dismissed keyboard.
    if (!editable(node)) report(false, reason);
  }
  document.addEventListener('pointerdown', event => {
    if (!event.isTrusted) return;
    clearTimeout(pending);
    let node = event.composedPath().find(item => item instanceof Element);
    const label = node?.closest('label');
    if (label?.control) node = label.control;
    // xterm renders text in a canvas/rows and receives keyboard input through
    // a separate textarea. A trusted tap in its screen is an editing gesture.
    if (terminalInput(node)) return;
    // Repeat taps reopen an already-focused field after manual IME dismissal.
    report(editable(node), 'pointer');
  }, {capture: true, signal});
  document.addEventListener('click', event => {
    if (!event.isTrusted) return;
    const node = event.composedPath().find(item => item instanceof Element);
    const input = terminalInput(node);
    if (!input || document.visibilityState !== 'visible') return;
    // Touch generates an emulated mousedown after pointerup. Waiting for click
    // lets that default focus action finish before selecting xterm's input.
    clearTimeout(pending);
    input.focus({preventScroll: true});
    report(true, 'pointer');
  }, {signal});
  document.addEventListener('focusin', () => {
    clearTimeout(pending);
    reportCurrent('focus');
  }, {capture: true, signal});
  document.addEventListener('focusout', () => {
    clearTimeout(pending);
    // Let focus move between fields before deciding whether to dismiss the keyboard.
    pending = setTimeout(() => reportCurrent('blur'), 0);
  }, {capture: true, signal});
  document.addEventListener('visibilitychange', () => {
    clearTimeout(pending);
    // Native IME/X11 layout can briefly hide the web contents while its editor
    // is retained. Native Activity pause handles actually leaving the app.
    reportCurrent(document.visibilityState === 'visible' ? 'resume' : 'hidden');
  }, {signal});
  window.addEventListener('focus', () => {
    clearTimeout(pending);
    // Entering an iframe focuses its window before its input. Let that focusin
    // settle before a body activeElement can dismiss the user's pointer request.
    pending = setTimeout(() => reportCurrent('window-focus'), 0);
  }, {signal});
  window.addEventListener('blur', () => {
    clearTimeout(pending);
    pending = setTimeout(() => {
      if (!document.hasFocus()) reportCurrent('window-blur');
    }, 0);
  }, {signal});
  const instance = {
    editing: () => editable(active()),
    resync: () => reportCurrent('attach'),
    dispose: () => {
      disposed = true;
      clearTimeout(pending);
      controller.abort();
      if (globalThis[key] === instance) delete globalThis[key];
      if (globalThis.__codexImeHook === instance) delete globalThis.__codexImeHook;
    }
  };
  globalThis[key] = instance;
  globalThis.__codexImeHook = instance;
  reportCurrent('attach');
  return 'installed';
})();
