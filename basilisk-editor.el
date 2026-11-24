;;; basilisk-editor.el --- Basilisk C: major mode and language server  -*- lexical-binding: t; -*-

;; Copyright (C) 2026 the basilisk-editor contributors

;; URL: https://github.com/Riccaraccio/basilisk-editor
;; Version: 0.1.0
;; Package-Requires: ((emacs "29.1"))
;; Keywords: languages, c

;; This program is free software: you can redistribute it and/or modify
;; it under the terms of the GNU General Public License as published by
;; the Free Software Foundation, either version 3 of the License, or
;; (at your option) any later version.  See LICENSE.

;;; Commentary:

;; Support for Basilisk C (http://basilisk.fr) source files:
;;
;; - `basilisk-c-mode', a `c-mode' with Basilisk keywords highlighted
;;   (foreach loops, events, reductions, fields, built-ins);
;; - Basilisk .c/.h files are recognised by their content (events,
;;   foreach loops, field declarations, Basilisk includes), so plain C
;;   files keep `c-mode';
;; - the Basilisk language server (bin/basilisk-lsp, shipped with this
;;   package) is started with eglot (built into Emacs 29) or lsp-mode:
;;   qcc diagnostics, completion, hover documentation, go to
;;   definition, imenu/outline;
;; - M-x compile runs the qcc check (`compile-command').
;;
;; Project settings (qcc flags, grid...) live in .basilisk-lsp.json, see
;; README.md.  Basilisk's own basilisk-mode.el (literate markdown
;; comments) can be used instead of `basilisk-c-mode': the language
;; server is registered for both.

;;; Code:

(require 'cc-mode)

(defgroup basilisk nil
  "Basilisk C support."
  :group 'languages
  :prefix "basilisk-")

(defconst basilisk-editor-directory
  (file-name-directory (or load-file-name buffer-file-name default-directory))
  "Directory of the basilisk-editor package.")

(defcustom basilisk-lsp-command
  (list (expand-file-name "bin/basilisk-lsp" basilisk-editor-directory))
  "Command starting the Basilisk language server."
  :type '(repeat string))

(defcustom basilisk-lsp-options nil
  "Settings sent to the language server, as a plist.
For example (:diagnostics \"onChange\").  Settings in the project file
.basilisk-lsp.json take precedence."
  :type 'plist)

(defcustom basilisk-auto-lsp 'eglot
  "Language server client started in Basilisk buffers.
`eglot' (built into Emacs 29), `lsp-mode', or nil for none."
  :type '(choice (const eglot) (const lsp-mode) (const :tag "None" nil)))

(defcustom basilisk-detect t
  "When non-nil, .c/.h files which look like Basilisk C use `basilisk-c-mode'."
  :type 'boolean)

;;;###autoload
(defun basilisk-buffer-p ()
  "Non-nil if the current .c/.h buffer looks like Basilisk C."
  (and (or (not (boundp 'basilisk-detect)) basilisk-detect)
       buffer-file-name
       (string-match-p "\\.[ch]\\'" buffer-file-name)
       (save-excursion
         (save-restriction
           (widen)
           (goto-char (point-min))
           (save-match-data
             (re-search-forward
              (concat
               "^[ \t]*\\(?:"
               "event[ \t]+[A-Za-z_][A-Za-z0-9_]*[ \t]*("
               "\\|#[ \t]*include[ \t]*\"\\(?:navier-stokes\\|grid\\|two-phase\\|vof\\|"
               "saint-venant\\|layered\\|embed\\|tension\\|run\\|utils\\|output\\|view\\|"
               "fractions\\|axi\\|reduced\\|curvature\\|tracer\\|diffusion\\|poisson\\|"
               "green-naghdi\\|compressible\\|bcg\\|advection\\|atmosphere\\|momentum\\|"
               "contact\\|heights\\|common\\)[/.]"
               "\\|\\(?:\\(?:face\\|vertex\\|symmetric\\)[ \t]+\\)?\\(?:scalar\\|vector\\|tensor\\)"
               "[ \t]+\\*?[ \t]*[A-Za-z_][A-Za-z0-9_]*[ \t]*\\[\\]"
               "\\|foreach\\(?:_[A-Za-z0-9_]+\\)?[ \t]*("
               "\\)")
              (save-excursion (forward-line 500) (point)) t))))))

;;;###autoload
(add-to-list 'magic-mode-alist '(basilisk-buffer-p . basilisk-c-mode))

(defconst basilisk-font-lock-keywords
  `((,(rx bol (group "event") (+ blank) (group (any alpha "_") (* (any alnum "_"))))
     ;; override: cc-mode takes "event init" for a declaration
     (1 font-lock-keyword-face t) (2 font-lock-function-name-face t))
    (,(rx bol "event" (+ blank) (* nonl) symbol-start (group (or "first" "last" "end")) symbol-end)
     (1 font-lock-constant-face))
    (,(rx symbol-start (or "foreach" (seq "foreach_" (+ (any alnum "_"))) "reduction") symbol-end)
     . font-lock-keyword-face)
    (,(rx symbol-start (or "scalar" "vector" "tensor" "coord" "Point") symbol-end)
     . font-lock-type-face)
    (,(rx (or (seq symbol-start (or "face" "vertex" "symmetric" "trace" "macro" "new" "delete")
                   symbol-end)
              "(const)"))
     . font-lock-keyword-face)
    (,(rx symbol-start (or "Delta" "point" "dimension") symbol-end)
     . font-lock-builtin-face)
    (,(rx symbol-start (or "left" "right" "top" "bottom" "front" "back" "nodata") symbol-end)
     . font-lock-constant-face)
    (,(rx symbol-start (or "dirichlet" "neumann" "dirichlet_homogeneous" "neumann_homogeneous"
                           "periodic" "val" "fine" "coarse" "neighbor")
          symbol-end (* blank) "(")
     . font-lock-builtin-face))
  "Basilisk additions to the C font-lock keywords.")

(defun basilisk-lint-command ()
  "Shell command checking the current file with qcc."
  (concat (mapconcat #'shell-quote-argument basilisk-lsp-command " ")
          " --lint " (shell-quote-argument (or buffer-file-name ""))))

(defun basilisk--start-lsp ()
  "Start the client chosen by `basilisk-auto-lsp'."
  (pcase basilisk-auto-lsp
    ('eglot (when (require 'eglot nil t) (eglot-ensure)))
    ('lsp-mode (when (require 'lsp-mode nil t) (lsp-deferred)))))

;;;###autoload
(define-derived-mode basilisk-c-mode c-mode "Basilisk-C"
  "Major mode for Basilisk C (http://basilisk.fr) source files.
\\{basilisk-c-mode-map}"
  (font-lock-add-keywords nil basilisk-font-lock-keywords 'prepend)
  (setq-local compile-command (basilisk-lint-command))
  (when buffer-file-name
    (add-hook 'after-change-major-mode-hook #'basilisk--start-lsp-once nil t)))

(defun basilisk--start-lsp-once ()
  "Start the language server once the mode hooks have run."
  (remove-hook 'after-change-major-mode-hook #'basilisk--start-lsp-once t)
  (basilisk--start-lsp))

;;; eglot

(defun basilisk--eglot-contact (&rest _)
  "Command line (and options) of the language server, for eglot."
  (append basilisk-lsp-command
          (when basilisk-lsp-options
            (list :initializationOptions basilisk-lsp-options))))

(with-eval-after-load 'eglot
  (defvar eglot-server-programs)
  (add-to-list 'eglot-server-programs
               '((basilisk-c-mode basilisk-mode) . basilisk--eglot-contact)))

;;; lsp-mode

(declare-function lsp-register-client "lsp-mode")
(declare-function make-lsp-client "lsp-mode")
(declare-function lsp-stdio-connection "lsp-mode")
(declare-function lsp-activate-on "lsp-mode")
(declare-function lsp-deferred "lsp-mode")
(declare-function eglot-ensure "eglot")

(with-eval-after-load 'lsp-mode
  (defvar lsp-language-id-configuration)
  (add-to-list 'lsp-language-id-configuration '(basilisk-c-mode . "basilisk"))
  (add-to-list 'lsp-language-id-configuration '(basilisk-mode . "basilisk"))
  (lsp-register-client
   (make-lsp-client
    :new-connection (lsp-stdio-connection (lambda () basilisk-lsp-command))
    :activation-fn (lsp-activate-on "basilisk")
    :initialization-options (lambda () basilisk-lsp-options)
    :server-id 'basilisk-lsp)))

(provide 'basilisk-editor)
;;; basilisk-editor.el ends here
