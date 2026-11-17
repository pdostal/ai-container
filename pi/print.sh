#!/usr/bin/env bash
# pi-print: pi in print mode, loading only the extensions a one-shot run can use.
#
# pi imports every discovered extension before the first token, sequentially, so
# the full set costs ~3.8s of a ~4.2s startup. Most of that is invisible to `-p`:
# usage/quota status bars, the powerline footer, plan-mode UI, the btw side
# thread and the interactive-shell overlay all draw or drive a TUI that print
# mode never renders. This wrapper runs pi with `--no-extensions` plus the
# curated list in ~/.pi/print-mode-extensions, which keeps startup near 2s.
#
#   pi-print "summarize this repo"        # -p is added when no mode flag is given
#   pi-print -p --model x "hi"            # any other pi argument is forwarded
#   pi-print -ne ...                      # explicit extension flags: no trimming
#
# PI_PRINT_EXTENSIONS overrides the list path.
set -euo pipefail

builtin_list=/usr/local/share/pi/print-mode-extensions
list=${PI_PRINT_EXTENSIONS:-${HOME}/.pi/print-mode-extensions}
if [[ ! -r ${list} ]]; then
    list=${builtin_list}
fi

print_mode=false
for arg in "$@"; do
    case ${arg} in
        -p | --print | --json | --rpc) print_mode=true ;;
        -ne | --no-extensions | -e | --extension | --extension=*)
            # The caller picked extensions themselves; do not second-guess it.
            exec pi "$@"
            ;;
    esac
done

trimmed=()
if [[ -r ${list} ]]; then
    while IFS= read -r line; do
        line=${line%%#*}
        line=${line#"${line%%[![:space:]]*}"}
        line=${line%"${line##*[![:space:]]}"}
        if [[ -z ${line} ]]; then
            continue
        fi
        # shellcheck disable=SC2088  # matching the literal "~/" prefix on purpose
        case ${line} in
            "~/"*) line=${HOME}/${line#"~/"} ;;
        esac
        # A package the user never installed must not abort the run.
        if [[ ${line} == builtin:* || -e ${line} ]]; then
            trimmed+=(-e "${line}")
        fi
    done <"${list}"
fi

if [[ ${print_mode} == true ]]; then
    exec pi --no-extensions "${trimmed[@]}" "$@"
fi
exec pi --no-extensions "${trimmed[@]}" -p "$@"
