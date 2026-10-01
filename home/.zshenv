# Environment needed by interactive shells and Zsh scripts; keep this quiet.
# Ubuntu's global zshrc otherwise initializes completion before our custom fpath,
# causing two compinit calls to repeatedly invalidate the same dump file.
[[ -o interactive ]] && skip_global_compinit=1

if [[ -r "$HOME/.cargo/env" ]]; then
  source "$HOME/.cargo/env"
fi
