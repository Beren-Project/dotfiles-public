# Interactive Zsh configuration. Dependencies are installed separately.
[[ -o interactive ]] || return 0

# Environment: .zshenv owns the base PATH; Neovim is an interactive preference.
typeset -U path fpath
[[ -d /opt/nvim-linux-x86_64/bin ]] && path=(/opt/nvim-linux-x86_64/bin "${path[@]}")
export PATH

# History shared across terminals; a leading space excludes a command.
HISTFILE="$HOME/.zsh_history"
HISTSIZE=10000
SAVEHIST=10000
setopt APPEND_HISTORY SHARE_HISTORY HIST_IGNORE_DUPS HIST_IGNORE_SPACE HIST_REDUCE_BLANKS
setopt INTERACTIVE_COMMENTS
unsetopt INC_APPEND_HISTORY INC_APPEND_HISTORY_TIME

# Completion: compinit -i ignores insecure directories rather than trusting them.
[[ -d "$HOME/.zfunc" ]] && fpath=("$HOME/.zfunc" $fpath)
zmodload zsh/complist
autoload -Uz compinit
compinit -i
# Snapshot of this machine's eza 0.23.5 palette; no subprocess at startup.
# Cover basic file kinds and common extensions, retaining menu reverse video.
zstyle ':completion:*' list-colors \
  'no=0' 'fi=0' 'di=1;34' 'ln=36' 'or=36' 'ex=1;32' \
  'pi=33' 'so=31' 'bd=1;33' 'cd=1;33' 'su=1;32' 'sg=1;32' \
  'tw=1;34' 'ow=1;34' 'st=1;34' 'mi=0' \
  '*.'{png,jpg,jpeg,gif,svg,webp,bmp,tiff,ico}'=35' \
  '*.'{mp4,mkv,avi,mov,webm,flv,wmv}'=1;35' \
  '*.'{mp3,ogg,m4a,aac}'=36' '*.'{flac,wav,alac}'=1;36' \
  '*.'{pdf,doc,docx,odt,xls,xlsx,ods,ppt,pptx,odp}'=32' \
  '*.'{zip,tar,gz,bz2,xz,zst,7z,rar,tgz}'=31' \
  '*.'{py,rs,c,h,cpp,hpp,cc,java,js,jsx,ts,go,rb,lua,jl}'=1;33' \
  '*.'{tmp,swp,swo,bak}'=2' '*~=2' \
  '=(#i)(readme*|makefile|gnumakefile|cmakelists.txt|cargo.toml|package.json)=1;4;33'
zstyle ':completion:*' menu select
zstyle ':completion:*' matcher-list 'm:{a-zA-Z}={A-Za-z}'
bindkey -e

# Optional developer integrations.
# Avoid populating Zsh's full command table across Windows PATH directories.
if command -v eza >/dev/null 2>&1; then
  alias ls='eza'
  alias la='eza -la'
  alias ll='eza -ll'
fi

# WSL local-file launchers. Resolve tools only when invoked, not at startup.
if [[ -n ${WSL_DISTRO_NAME:-} ]]; then
  _wsl_open_file() {
    local browser=$1
    shift
    local label=${browser/msedge/edge}
    if (( $# != 1 )); then
      print -u2 -- "usage: $label <file>"
      return 1
    fi
    local resolved file executable relative candidate
    resolved=$(realpath -e -- "$1") || return 1
    if [[ ! -f $resolved ]]; then
      print -u2 -- "Not a regular file: $1"
      return 1
    fi
    file=$(wslpath -w "$resolved") || return 1
    case $browser in
      msedge) relative='Microsoft/Edge/Application/msedge.exe' ;;
      chrome) relative='Google/Chrome/Application/chrome.exe' ;;
      *) print -u2 -- "Unsupported browser: $browser"; return 1 ;;
    esac
    executable=$(whence -p "$browser.exe")
    if [[ -z $executable ]]; then
      for candidate in "/mnt/c/Program Files/$relative" "/mnt/c/Program Files (x86)/$relative"; do
        if [[ -f $candidate && -x $candidate ]]; then
          executable=$candidate
          break
        fi
      done
    fi
    if [[ -z $executable ]]; then
      print -u2 -- "Cannot find $browser.exe; add its installation directory to PATH."
      return 1
    fi
    # Direct argv passing avoids CMD expansion; do not wait for the browser UI.
    "$executable" "$file" </dev/null >/dev/null 2>&1 &!
  }
  edge() { _wsl_open_file msedge "$@"; }
  chrome() { _wsl_open_file chrome "$@"; }
fi

[[ -r "$HOME/.julia/juliaup/completions/zsh.zsh" ]] && source "$HOME/.julia/juliaup/completions/zsh.zsh"
if command -v fnm >/dev/null 2>&1 && _dotfiles_fnm_env=$(fnm env --use-on-cd --shell zsh); then
  # Generate first: failure must leave the existing fnm PATH untouched.
  for _dotfiles_fnm_bin in "${path[@]}"; do
    if [[ $_dotfiles_fnm_bin == /* && ${_dotfiles_fnm_bin:t} == bin &&
          ${_dotfiles_fnm_bin:h:h:t} == fnm_multishells ]]; then
      path=("${(@)path:#"$_dotfiles_fnm_bin"}")
    fi
  done
  eval "$_dotfiles_fnm_env"
fi
unset _dotfiles_fnm_env _dotfiles_fnm_bin
command -v direnv >/dev/null 2>&1 && eval "$(direnv hook zsh)"
command -v zoxide >/dev/null 2>&1 && eval "$(zoxide init zsh)"
# fzf 0.48.0+ embeds integration; apply only successfully generated output.
if [[ -o zle && -t 0 ]] && command -v fzf >/dev/null 2>&1 &&
    _dotfiles_fzf_env=$(fzf --zsh); then
  eval "$_dotfiles_fzf_env"
fi
unset _dotfiles_fzf_env
export MERMAID_FILTER_PUPPETEER_CONFIG="$HOME/.config/mermaid/pptr.json"
command -v mmdc >/dev/null 2>&1 && alias mmdc='mmdc -p "$MERMAID_FILTER_PUPPETEER_CONFIG"'

# Prompt: retain Starship's appearance and collapse completed input to an arrow.
PROMPT='%n@%m %~ %# '
if command -v starship >/dev/null 2>&1; then
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
