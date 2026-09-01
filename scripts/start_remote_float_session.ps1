[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$SshHost,

    [int]$SshPort = 22,
    [string]$SshUser = "root",
    [string]$RemoteWorkerRoot = "/workspace/virtual-teacher-worker",
    [int]$LocalTunnelPort = 18011,
    [int]$RemoteWorkerPort = 8011
)

# Compatibility entry retained for the previously documented command.
& "$PSScriptRoot\remote_float\01_start_session.ps1" @PSBoundParameters
exit $LASTEXITCODE
