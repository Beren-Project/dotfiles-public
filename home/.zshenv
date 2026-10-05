# Environment needed by interactive shells and Zsh scripts; keep this quiet.
# Ubuntu's global zshrc otherwise initializes completion before our custom fpath,
# causing two compinit calls to repeatedly invalidate the same dump file.
[[ -o interactive ]] && skip_global_compinit=1

typeset -U path
if [[ -r "$HOME/.cargo/env" ]]; then
  source "$HOME/.cargo/env"
fi

# Cargo owns developer tools; personal scripts follow inherited Linux/WSL paths.
[[ -d "$HOME/.cargo/bin" ]] && path=("$HOME/.cargo/bin" "${path[@]}")
path=("${(@)path:#"$HOME/bin"}")
path=("${(@)path:#"$HOME/.local/bin"}")
[[ -d "$HOME/bin" ]] && path+=("$HOME/bin")
[[ -d "$HOME/.local/bin" ]] && path+=("$HOME/.local/bin")
export PATH
