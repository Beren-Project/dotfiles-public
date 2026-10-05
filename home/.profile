# ~/.profile: executed by the command interpreter for login shells.
# This file is not read by bash(1), if ~/.bash_profile or ~/.bash_login
# exists.
# see /usr/share/doc/bash/examples/startup-files for examples.
# the files are located in the bash-doc package.

# the default umask is set in /etc/profile; for setting the umask
# for ssh logins, install and configure the libpam-umask package.
#umask 022

# Build the login environment before interactive Bash integrations run.
# Preserve non-empty inherited ordering, including paths containing spaces.
_dotfiles_path_rest=${PATH-}:
_dotfiles_login_path=
_dotfiles_path_started=
while [ -n "$_dotfiles_path_rest" ]; do
    _dotfiles_path_entry=${_dotfiles_path_rest%%:*}
    _dotfiles_path_rest=${_dotfiles_path_rest#*:}
    case $_dotfiles_path_entry in
        ""|"$HOME/.cargo/bin"|"$HOME/bin"|"$HOME/.local/bin") continue ;;
    esac
    if [ -n "$_dotfiles_path_started" ]; then
        case :$_dotfiles_login_path: in
            *:"$_dotfiles_path_entry":*) continue ;;
        esac
        _dotfiles_login_path=$_dotfiles_login_path:$_dotfiles_path_entry
    else
        _dotfiles_login_path=$_dotfiles_path_entry
        _dotfiles_path_started=yes
    fi
done
PATH=$_dotfiles_login_path
[ -r "$HOME/.cargo/env" ] && . "$HOME/.cargo/env"
# Cargo's generated environment can leave a trailing colon when PATH was empty.
PATH=${PATH%:}
case :$PATH: in
    *:"$HOME/.cargo/bin":*) ;;
    *) [ -d "$HOME/.cargo/bin" ] && PATH="$HOME/.cargo/bin${PATH:+:$PATH}" ;;
esac
[ -d "$HOME/bin" ] && PATH="${PATH:+$PATH:}$HOME/bin"
[ -d "$HOME/.local/bin" ] && PATH="${PATH:+$PATH:}$HOME/.local/bin"
export PATH
unset _dotfiles_path_rest _dotfiles_login_path _dotfiles_path_started _dotfiles_path_entry

if [ -n "${BASH_VERSION:-}" ] && [ -r "$HOME/.bashrc" ]; then
    . "$HOME/.bashrc"
fi

# Keep startup successful when optional tools are absent.
true
