[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$SshHost,

    [int]$SshPort = 22,
    [string]$SshUser = "root",
    [string]$RemoteWorkerRoot = "/workspace/virtual-teacher-worker"
)

$ErrorActionPreference = "Stop"

if ($RemoteWorkerRoot -notmatch '^/[A-Za-z0-9._/-]+$') {
    throw "RemoteWorkerRoot contains unsupported shell characters."
}

$target = "${SshUser}@${SshHost}"
$remoteCommand = "cd '${RemoteWorkerRoot}' && bash stop_worker.sh"

& ssh -p $SshPort.ToString() $target $remoteCommand
if ($LASTEXITCODE -ne 0) {
    throw "SSH command exited with code $LASTEXITCODE."
}
