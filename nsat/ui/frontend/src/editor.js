// CodeMirror 6 打包入口：暴露全局 NSATEditor
import { EditorView, keymap, lineNumbers, highlightActiveLine, drawSelection } from "@codemirror/view";
import { EditorState, Compartment } from "@codemirror/state";
import { defaultKeymap, history, historyKeymap, indentWithTab, redo, undo, deleteCharForward, selectAll } from "@codemirror/commands";
import { syntaxHighlighting, defaultHighlightStyle, indentOnInput, bracketMatching, foldGutter, foldKeymap, indentUnit } from "@codemirror/language";
import { autocompletion, completionKeymap, closeBrackets, closeBracketsKeymap } from "@codemirror/autocomplete";
import { oneDark } from "@codemirror/theme-one-dark";
import { python } from "@codemirror/lang-python";
import { javascript } from "@codemirror/lang-javascript";
import { go } from "@codemirror/lang-go";
import { rust } from "@codemirror/lang-rust";
import { cpp } from "@codemirror/lang-cpp";
import { java } from "@codemirror/lang-java";

const langCompartment = new Compartment();

function langFor(mode) {
  mode = (mode || "").toLowerCase();
  if (mode.startsWith("py")) return python();
  if (mode.startsWith("js") || mode.startsWith("ts") || mode === "javascript") return javascript();
  if (mode === "go" || mode === "golang") return go();
  if (mode === "rust" || mode === "rs") return rust();
  if (mode === "c" || mode === "cpp" || mode === "c++") return cpp();
  if (mode === "java") return java();
  return null;
}

window.NSATEditor = {
  create(parent, { value = "", mode = "text", onChange = null, readOnly = false }) {
    const state = EditorState.create({
      doc: value,
      extensions: [
        lineNumbers(),
        highlightActiveLine(),
        drawSelection(),
        history(),
        foldGutter(),
        indentOnInput(),
        bracketMatching(),
        closeBrackets(),
        autocompletion(),
        syntaxHighlighting(defaultHighlightStyle, { fallback: true }),
        oneDark,
        EditorState.tabSize.of(4),
        indentUnit.of("    "),
        langCompartment.of(langFor(mode) || []),
        EditorView.lineWrapping,
        readOnly ? EditorState.readOnly.of(true) : [],
        keymap.of([...closeBracketsKeymap, ...defaultKeymap, ...historyKeymap, ...foldKeymap, ...completionKeymap, indentWithTab]),
        EditorView.updateListener.of((u) => {
          if (onChange && u.docChanged) onChange(u.state.doc.toString());
        }),
      ],
    });
    const view = new EditorView({ state, parent });
    return {
      getValue() { return view.state.doc.toString(); },
      setValue(v) {
        if (v === view.state.doc.toString()) return;
        view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: v } });
      },
      setMode(m) {
        view.dispatch({ effects: langCompartment.reconfigure(langFor(m) || []) });
      },
      focus() { view.focus(); },
      destroy() { view.destroy(); },
      commands: {
        undo: () => { view.focus(); return undo(view); },
        redo: () => { view.focus(); return redo(view); },
        copy: async () => {
          const { from, to } = view.state.selection.main;
          const text = view.state.sliceDoc(from, to);
          if (!text) return;
          try { await navigator.clipboard.writeText(text); } catch (e) {}
        },
        cut: async () => {
          const { from, to } = view.state.selection.main;
          const text = view.state.sliceDoc(from, to);
          if (!text) return;
          try { await navigator.clipboard.writeText(text); } catch (e) {}
          view.dispatch({ changes: { from, to, insert: "" } });
          view.focus();
        },
        paste: async () => {
          try {
            const text = await navigator.clipboard.readText();
            if (text == null) return;
            view.dispatch(view.state.replaceSelection(text));
            view.focus();
          } catch (e) {}
        },
        deleteSelection: () => {
          const { from, to } = view.state.selection.main;
          if (from !== to) view.dispatch({ changes: { from, to, insert: "" } });
          else deleteCharForward(view);
          view.focus();
        },
        selectAll: () => { view.focus(); return selectAll(view); },
      },
    };
  },
};
