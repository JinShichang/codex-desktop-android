# Changelog

## 2026-11-27 — Probe PRoot seccomp acceleration before use

- Select acceleration using a bounded, side-effect-free nested-exec probe under the actual Android app or Python tool entrypoint. A passing probe must also observe PRoot's acceleration banner.
- Validate the compatible path before disabling acceleration. If both probes fail, stop before running the installer or user command; never retry user work automatically.
- Cache results separately for Java and Python callers, keyed by system and native runtime identity. Reprobe after ROM, kernel, APK native library or rootfs changes.
- Include the policy module in APK assets and load it by its installed path with Python isolation enabled. Preserve the managed GNU executor's existing fixed syscall-translation policy.
- Add JVM and Linux Python regressions for selection, cache invalidation, bounded cleanup and isolated tool startup. Android device validation remains pending.

## 2026-11-15 — IME stability and desktop high refresh

- Keep a retained editor open through transient Electron visibility/context changes; validate passive hide requests using focus metadata and reject stale replies after a newer user gesture. Outside taps and native Activity pause still dismiss normally.
- Clear the X11 surface's self-locking current-rate vote. While the desktop Activity is resumed, prefer the fastest mode at the same physical resolution and release the preference on pause. X11 continues following the actual selected display mode.
- Add transient-context, user-intent race and resolution-preserving refresh selection regressions.
- Bundle and refresh both guest IME files during existing-container startup, so APK updates also deploy the bridge fix.

## 2026-11-15 — Live work detection and continuous glow

- Use the launcher's transparent mark for every notification; remove action-dependent system icons and the obsolete two-bar mark.
- Recognize suffixed rollout filenames while retaining the canonical thread ID. Handle current `response_item` tool calls and `item_completed` events so ordinary checkout/build work is observed too.
- Replace the five outline bands with a continuous GPU falloff and spatial dithering on Android 13+, retaining the 50 dp stroke and 900 ms cycle. Older Android uses a finer 64-layer fallback.
- Follow display mode refresh changes in the X11 surface without requiring a resize. Request Android's high-refresh scheduling category while visible, clear it on pause, and remove the old beam's fixed frame throttle.

## 2026-11-14 — Phone effects and readable live actions

- Restore the original screen-edge glow through the current overlay lifecycle, with twice the stroke widths and a 900 ms rotation period (previously 9 seconds).
- Use the overlay's action text in the phone live card, with current app, recent steps, pause/continue and task-bound stop controls.
- Prefer phone activity over the general Codex live notification across the separate runtime process; restore general work status when the phone task ends.
- Show complete compact action phrases and full expanded details instead of sliding five-character fragments. Use action-specific notification icons where supported by the system.
- Keep the ColorOS presentation on the standard Android Live Updates path; the separate OML service template is not embedded in this native app.

## 2026-11-14 — Workstation handoff and live status source update

- Target Linux ARM64 desktop `26.1111.21308` and GNU Codex `0.169.0`; preserve the prior device qualification as a separate baseline.
- Update the vendored native dsh-Go driver and adapt its ownership, focus input and visual interfaces to the Codex host.
- Request system Live Updates for real Codex work and phone control, scroll the compact status, and bind stop actions to the original phone task.
- Disable the extra Xfwm compositor while retaining Electron's GPU rendering and the window manager.
- Build the paired GNU backend and local versionCode 57 APK in WSL using the original signing certificate. Include the Android 13+ accessibility input-method configuration required by focus input. Desktop installation, system island behavior and performance still await device qualification.

## 2026-10-20 — Supply-chain hardening

- Checkout without persisted credentials; GitHub Actions stay pinned by commit SHA; zizmor clean
  (vendored upstream workflows, which never run here, are ignored in `.github/zizmor.yml`).
- Dependabot for GitHub Actions with a 7-day cooldown; OpenSSF Scorecard workflow and README badge.

## 2026-10-14 — OpenAI Codex upstream alignment & documentation badges

- Add OpenAI Codex Desktop and repository stargazer badges to primary documentation.
- Establish active Q4 2026 engineering track focusing on upstream OpenAI runtime compatibility and automated ARM64 PRoot verification.
- Open public issue tracker roadmap items for upstream client synchronization and Android 15/16 test automation.

## 2026-09-11 — Recovery after Android terminates the native owner

- Fix an indefinite “Reprise de ChatGPT” state after Android kills the native
  owner while its Java service survives. Persist recovery intent, retire that
  Android runtime process and require complete quiescence before the next owner.
- Qualify r48/versionCode38 on the Fold with an owner-only SIGKILL: automatic
  recovery observed within 45 seconds, original marker and project/history bytes
  preserved, and real Android keyboard input verified after recovery.
- Add nine lifecycle regressions; 67 JVM lifecycle tests pass. Android's global
  process limit is unchanged, and peak process use remains a release requirement.

## Unreleased — Daily-use stabilization

- Retire Java executor workers after native cleanup and bind conversation/connector
  activations to their workspace generation, waiting for actual child exits.
- Refuse unknown official-client bytes and forged adapter receipts; recover
  interrupted ASAR publication. Deliver the admission-first guest launcher with
  the adapter in the APK.
- Build versionCode37 qualification candidates from explicit, inventoried native
  and toolchain inputs with APK content, source-closure and signing checks.
- Add concurrency and failure regressions to CI, an identity-bound read-only
  device baseline, and measurable daily-use/system-preservation gates.
- Prioritize dependable sessions, reproducible installation and safe client
  updates. Fresh installation and extended device qualification remain pending.

## 2026-09-11 — Showcase graphics recovery

- Preserve the static capture and disable unavailable 3D controls after graphics initialization or restoration failures.
- Clean up partial GPU resources, ignore stale texture callbacks and restore controls after successful recovery.
- Add seven scene lifecycle regression tests to public CI.

## 2026-09-11 — Fold8 handset and Remote cover display

- Correct the showcase model to Samsung's standard Galaxy Z Fold8 rear layout, with two cameras behind the right half of the inner display and the cover display behind the other half.
- Fix outward surface orientation and centered folding; add solid sidewalls to the camera island and lens rings.
- Show OpenAI's official Remote preview on the cover display, with readable text and preserved image proportions; document its provenance separately from the authentic Fold captures.

## 2026-09-11 — Repository maintenance

- Remove superseded Termux/QEMU launchers, one-off live-CDP experiments, the old launcher app and outdated publication drafts.
- Group maintained guest sources under `runtime/guest/` with byte-identical generated bundles; retain the compatibility shim and diagnostics under `compat/desktop-sandbox/`.
- Separate historical audits and release records from the root documentation; retain meaningful regression tests and document their prerequisites.
- Repair native PRoot regression runners for source-only checkouts and include additional existing host regression suites in the standard runner.
- Refresh the showcase screenshot in the README, ignore disposable test caches and document the source layout.

Notable changes to Codex are recorded here. Source preview versions describe the published implementation and its documentation; they do not certify a consumer installation or every device workflow.

## [Unreleased]

### Showcase and documentation

- Record the maintainer’s confirmation that Samsung Pay works on the development Fold in the showcase and compatibility documentation.

- Focus showcase copy on Codex, local projects, workspace tools and Android input; remove visible animation narration and capture-production notes while preserving image credits, accessible controls and alpha limitations.

- Restore the authentic Codex composer and session controls in the gallery and 3D screen; anonymize only the account name as `you@gmail.com` and its avatar. Document the two direct pixel edits and unchanged original interface.

- Select the showcase language automatically from the browser's preferred language: French for French preferences, English otherwise, with no visible selector.

- Move the showcase into the Julien Piron portfolio at `https://julienpiron.fr/foldgpt/` and publish its static source under `site/`.
- Use the application's exact vector icon and graphite/gold identity in the website and repository artwork.
- Replace simulated demonstrations with historical device captures and explicit media provenance. The interactive handset remains clearly identified as a WebGL visualization.
- Introduce a particle handset with rotation, fold controls, dispersion and reassembly, plus accessible controls and reduced-motion support.
- Link the README and product documentation to the canonical portfolio page and its authentic capture gallery.
- Align public credits with the julienpiron.fr brand and add the faithful banner export used for Open Graph and X link previews, with localized alternative text.

## [0.2.0-alpha.1] — 2026-09-11

The first named source preview opens Codex to contributors: an Android host for the Linux ARM64 ChatGPT desktop client, with desktop Codex and local project tools on a Galaxy Z Fold.

### Experience and implementation

- Android host, embedded Termux:X11 display, touch and keyboard integration, and a separate runtime service with recovery and explicit-stop handling.
- Debian/PRoot compatibility environment and a native execution layer for local commands, project files, Git, Python, and Node workflows.
- ARM64 workspace integration for document creation and rendering, including demonstrated DOCX, PPTX, XLSX, and PDF workflows.
- Version-specific desktop workspace adaptation and source recovery records for the open-source Codex execution engine.
- Android bridge plugin and supporting source for permission-based device integrations.

### Source distribution

- Restore Android application, installer, shell-loader configuration, native execution helpers, and build inputs omitted from the earlier public snapshot.
- Record vendored Termux:X11 and PRoot source provenance and explain dependency licenses and proprietary-client acquisition.
- Require a complete, explicitly selected native executor package for production-candidate builds; verify its assets and JNI inventory before assembling the final APK.

### Fixes

- Repair the native workspace admission path whose fallback to a guest path produced `EACCES` during local command execution.

### Documentation and collaboration

- Add a product overview, architecture diagram, compatibility matrix, FAQ, roadmap, and a documentation entry point.
- Add contribution and security-reporting guidance, structured issue forms, and a pull-request template.
- Separate product support statements from dated development evidence and publication drafts.

### Release boundaries

- Source only: no consumer APK, preconfigured Linux image, proprietary client package, or account data is included.
- The demonstrated target is the development Galaxy Z Fold 8. Clean-device installation, updates, Remote, and sustained simultaneous/background sessions remain under qualification.
- Android's shared phantom-process budget still applies. Multiple ordinary APKs do not create separate budgets; reducing process pressure must preserve independent conversations.
- Desktop runtime, files, and tools run locally. Model inference uses OpenAI's online services.

[0.2.0-alpha.1]: https://github.com/pironjulien/FoldGPT/releases/tag/v0.2.0-alpha.1
