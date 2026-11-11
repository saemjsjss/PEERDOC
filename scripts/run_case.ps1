# Run the master pipeline (OCR -> extraction -> rules) from Windows PowerShell.
# The OCR models need the WSL GPU environment, so this hands over to WSL.
#
#   .\scripts\run_case.ps1 "C:\dcSS\SAMPLE DOC"
#   .\scripts\run_case.ps1 "C:\dcSS\SAMPLE DOC" --date 2026-11-11
#
# If PowerShell refuses to run scripts here (execution policy), use scripts\run_case.cmd,
# which starts this file with -ExecutionPolicy Bypass for that one run.
# Windows paths (absolute or relative) are accepted; run_case.py converts them.
# Exit code: 0 PASS, 1 FLAG, 2 FAIL, 3 error.

$repo = Split-Path -Parent $PSScriptRoot
$drive = $repo.Substring(0, 1).ToLower()
$wslRepo = "/mnt/$drive" + ($repo.Substring(2) -replace '\\', '/')

# Windows PowerShell 5.1 quotes an argument containing a space but does not double a
# trailing backslash, so "C:\x y\" reaches WSL as  C:\x y"  plus whatever follows.
# A trailing backslash means nothing in a folder path: drop it (but keep drive roots).
$forward = @(foreach ($a in $args) {
    $s = [string]$a
    if ($s -match '\\+$' -and $s -notmatch '^[A-Za-z]:\\$') { $s.TrimEnd('\') } else { $s }
})

wsl -d Ubuntu --exec bash "$wslRepo/scripts/wsl/run_case.sh" @forward
exit $LASTEXITCODE
