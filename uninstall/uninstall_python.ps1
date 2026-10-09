param(
    [Parameter(Mandatory = $true)]
    [string]$PythonMajorMinor
)

$ErrorActionPreference = "Stop"

function Split-UninstallCommand {
    param([string]$Command)

    $command = [Environment]::ExpandEnvironmentVariables($Command.Trim())

    if ($command.StartsWith('"')) {
        $closing = $command.IndexOf('"', 1)
        if ($closing -gt 1) {
            return @{
                File = $command.Substring(1, $closing - 1)
                Args = $command.Substring($closing + 1).Trim()
            }
        }
    }

    $firstSpace = $command.IndexOf(' ')
    if ($firstSpace -lt 0) {
        return @{ File = $command; Args = "" }
    }

    return @{
        File = $command.Substring(0, $firstSpace)
        Args = $command.Substring($firstSpace + 1)
    }
}

$registryPaths = @(
    "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*",
    "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*",
    "HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*"
)

$matches = foreach ($path in $registryPaths) {
    Get-ItemProperty $path -ErrorAction SilentlyContinue |
        Where-Object {
            $_.DisplayName -and
            $_.Publisher -like "*Python Software Foundation*" -and
            (
                $_.DisplayName -like "Python $PythonMajorMinor*" -or
                $_.DisplayName -like "Python $PythonMajorMinor.*"
            ) -and
            $_.UninstallString
        }
}

if (-not $matches) {
    Write-Host "No matching Python $PythonMajorMinor uninstall entry was found."
    exit 1
}

$success = $false

foreach ($entry in $matches) {
    Write-Host ("Removing: " + $entry.DisplayName)

    $parsed = Split-UninstallCommand $entry.UninstallString
    $file = $parsed.File
    $arguments = $parsed.Args

    if ($file -match "(?i)msiexec(\.exe)?$") {
        $arguments = $arguments -replace "(?i)(^|\s)/I(?=\s|\{)", '$1/X'
        if ($arguments -notmatch "(?i)/quiet|/qn") {
            $arguments += " /qn /norestart"
        }
    }
    elseif ($arguments -notmatch "(?i)/quiet|/silent") {
        $arguments += " /quiet"
    }

    try {
        $process = Start-Process -FilePath $file -ArgumentList $arguments -Wait -PassThru
        if ($process.ExitCode -eq 0 -or $process.ExitCode -eq 3010) {
            $success = $true
        }
    }
    catch {
        Write-Host $_.Exception.Message
    }
}

if ($success) {
    exit 0
}

exit 1
