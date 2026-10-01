# Interactive Zsh configuration. Dependencies are installed separately.
[[ -o interactive ]] || return 0

# Environment: .zshenv loads Cargo; keep PATH entries unique.
typeset -U path fpath
[[ -r "$HOME/.local/bin/env" ]] && source "$HOME/.local/bin/env"
for config_dir in /opt/nvim-linux-x86_64/bin "$HOME/.juliaup/bin" "$HOME/bin" "$HOME/.local/bin"; do
  [[ -d "$config_dir" ]] && path=("$config_dir" $path)
done
unset config_dir
export PATH

# History shared across terminals; a leading space excludes a command.
HISTFILE="$HOME/.zsh_history"
HISTSIZE=10000
SAVEHIST=10000
setopt APPEND_HISTORY SHARE_HISTORY HIST_IGNORE_DUPS HIST_IGNORE_SPACE HIST_REDUCE_BLANKS
unsetopt INC_APPEND_HISTORY INC_APPEND_HISTORY_TIME

# Completion: compinit -i ignores insecure directories rather than trusting them.
[[ -d "$HOME/.zfunc" ]] && fpath=("$HOME/.zfunc" $fpath)
autoload -Uz compinit
compinit -i
zstyle ':completion:*' menu select
zstyle ':completion:*' matcher-list 'm:{a-zA-Z}={A-Za-z}'
bindkey -e

# Optional developer integrations.
[[ -r "$HOME/.julia/juliaup/completions/zsh.zsh" ]] && source "$HOME/.julia/juliaup/completions/zsh.zsh"
(( $+commands[fnm] )) && eval "$(fnm env --use-on-cd --shell zsh)"
(( $+commands[direnv] )) && eval "$(direnv hook zsh)"
(( $+commands[zoxide] )) && eval "$(zoxide init zsh)"
if [[ -o zle && -t 0 ]] && (( $+commands[fzf] )); then
  [[ -r /usr/share/doc/fzf/examples/completion.zsh ]] && source /usr/share/doc/fzf/examples/completion.zsh
  [[ -r /usr/share/doc/fzf/examples/key-bindings.zsh ]] && source /usr/share/doc/fzf/examples/key-bindings.zsh
fi
export MERMAID_FILTER_PUPPETEER_CONFIG="$HOME/.config/mermaid/pptr.json"
(( $+commands[mmdc] )) && alias mmdc='mmdc -p "$MERMAID_FILTER_PUPPETEER_CONFIG"'

# Prompt: retain Starship's appearance and collapse completed input to an arrow.
PROMPT='%n@%m %~ %# '
if (( $+commands[starship] )); then
  autoload -Uz add-zsh-hook add-zle-hook-widget
  eval "$(starship init zsh)"
  _dotfiles_full_prompt=$PROMPT
  _dotfiles_full_rprompt=$RPROMPT
  _dotfiles_restore_prompt() {
    PROMPT=$_dotfiles_full_prompt
    RPROMPT=$_dotfiles_full_rprompt
  }
  # Runs after Starship captures status, before the next full prompt is drawn.
  add-zsh-hook precmd _dotfiles_restore_prompt
  _dotfiles_transient_prompt() {
    local transient
    transient=$(starship prompt --profile transient --keymap "${KEYMAP:-emacs}") || return 0
    # ZLE redraws after this hook returns; keep these values until precmd.
    PROMPT="$transient" RPROMPT=''
    zle .reset-prompt
  }
  add-zle-hook-widget zle-line-finish _dotfiles_transient_prompt
fi

# Standalone plugins. Missing plugins leave the basic shell usable.
_zsh_plugin_root="${XDG_DATA_HOME:-$HOME/.local/share}/zsh/plugins"
[[ -r "$_zsh_plugin_root/zsh-autosuggestions/zsh-autosuggestions.zsh" ]] && source "$_zsh_plugin_root/zsh-autosuggestions/zsh-autosuggestions.zsh"
[[ -r "$_zsh_plugin_root/zsh-history-substring-search/zsh-history-substring-search.zsh" ]] && source "$_zsh_plugin_root/zsh-history-substring-search/zsh-history-substring-search.zsh"

# Both common terminal arrow encodings; fall back to native history navigation.
for key_sequence in $'\e[A' $'\eOA'; do
  if (( $+widgets[history-substring-search-up] )); then
    bindkey "$key_sequence" history-substring-search-up
  else
    bindkey "$key_sequence" up-line-or-history
  fi
done
for key_sequence in $'\e[B' $'\eOB'; do
  if (( $+widgets[history-substring-search-down] )); then
    bindkey "$key_sequence" history-substring-search-down
  else
    bindkey "$key_sequence" down-line-or-history
  fi
done
unset key_sequence
# Configure your terminal to send ESC [ 13 ; 2 u for Shift+Enter.
_dotfiles_insert_newline() { LBUFFER+=$'\n'; }
zle -N _dotfiles_insert_newline
bindkey $'\e[13;2u' _dotfiles_insert_newline

# Syntax highlighting must follow other widget definitions.
[[ -r "$_zsh_plugin_root/zsh-syntax-highlighting/zsh-syntax-highlighting.zsh" ]] && source "$_zsh_plugin_root/zsh-syntax-highlighting/zsh-syntax-highlighting.zsh"
unset _zsh_plugin_root
true
