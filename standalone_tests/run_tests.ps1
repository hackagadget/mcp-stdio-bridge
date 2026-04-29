<#
.SYNOPSIS
    Orchestrates MCP Stdio Bridge standalone tests.
#>

param(
    [Parameter(Mandatory=$false)]
    [ValidateSet("local-mock", "start-bridge-sse", "test-sse", "ssh", "docker-local", "docker-sse", "docker-ssh-direct", "docker-ssh-proxy")]
    [string]$Test = "local-mock",

    [string]$SshHost = "user@remote-host",
    [string]$SshArgs = "",
    [string]$RemoteConfig = "/path/to/remote/config.yaml",
    [string]$SseUrl = "http://localhost:8000",
    [string]$ApiKey = "",

    [switch]$Help
)

if ($Help) {
    if ($PSBoundParameters.ContainsKey("Test")) {
        Write-Host ""
        switch ($Test) {
            "local-mock" {
                Write-Host "local-mock" -ForegroundColor Cyan
                Write-Host "  Run stdio wrapper test locally against mock WP-CLI."
                Write-Host "  No additional options."
            }
            "start-bridge-sse" {
                Write-Host "start-bridge-sse" -ForegroundColor Cyan
                Write-Host "  Generate config and start a local SSE bridge on port 8000."
                Write-Host "  Run test-sse in a separate terminal to send requests."
                Write-Host "  No additional options."
            }
            "test-sse" {
                Write-Host "test-sse" -ForegroundColor Cyan
                Write-Host "  Run SSE client test against a running local bridge."
                Write-Host ""
                Write-Host "  -SseUrl <url>   Base URL of the bridge  (default: http://localhost:8000)"
                Write-Host "  -ApiKey <key>   API key if authentication is configured  (default: none)"
            }
            "ssh" {
                Write-Host "ssh" -ForegroundColor Cyan
                Write-Host "  Run stdio test against a real remote host via SSH."
                Write-Host ""
                Write-Host "  -SshHost <user@host>   Remote host to connect to  (default: user@remote-host)"
                Write-Host "  -RemoteConfig <path>   Path to config.yaml on the remote host"
                Write-Host "  -SshArgs <args>        Extra arguments to pass to ssh  (optional)"
            }
            default {
                Write-Host "$Test" -ForegroundColor Cyan
                Write-Host "  No additional options."
            }
        }
        Write-Host ""
    } else {
        Write-Host "`nMCP Stdio Bridge Test Orchestrator" -ForegroundColor Cyan
        Write-Host "----------------------------------"
        Write-Host "Usage:"
        Write-Host "  .\run_tests.ps1 [-Test <scenario>] [options]"
        Write-Host "  .\run_tests.ps1 -Test <scenario> -Help  (show options for that scenario)`n"
        Write-Host "  Default: -Test local-mock`n"
        Write-Host "Local Scenarios:"
        Write-Host "  local-mock         Run stdio wrapper test locally against mock WP-CLI"
        Write-Host "  start-bridge-sse   Start a local SSE bridge (use with test-sse in another terminal)"
        Write-Host "  test-sse           Run SSE client test against a running local bridge"
        Write-Host "                     Options: -SseUrl <url>  -ApiKey <key>"
        Write-Host "  ssh                Run stdio test against a real remote host via SSH"
        Write-Host "                     Options: -SshHost <user@host>  -RemoteConfig <path>  -SshArgs <args>`n"
        Write-Host "Docker Scenarios:"
        Write-Host "  docker-local       Run local-mock test inside Docker"
        Write-Host "  docker-sse         Run SSE pipeline test inside Docker"
        Write-Host "  docker-ssh-direct  Run direct SSH scenario inside Docker"
        Write-Host "  docker-ssh-proxy   Run SSE-to-SSH proxy scenario inside Docker`n"
    }
    exit
}

$env:PYTHONPATH = "$(Resolve-Path "$PSScriptRoot\..")\src"
Push-Location $PSScriptRoot

$IsDockerTest = $Test -like "docker-*"

if ($IsDockerTest) {
    # Force non-interactive modes for Docker
    $env:COMPOSE_NO_TTY = "1"
    $env:COMPOSE_DOCKER_CLI_HINTS = "false"
    $env:DOCKER_SCAN_SUGGEST = "false"

    $Yaml = "docker-compose.test.yml"
    $Project = "mcp-test"

    function Invoke-Docker {
        param($ArgsList)
        $allArgs = @("-p", $Project, "-f", $Yaml, "--progress", "plain", "--ansi", "never") + $ArgsList
        & docker compose @allArgs
    }

    # Pre-test cleanup
    $null | docker compose -p $Project -f $Yaml down -v --timeout 0 --remove-orphans 2> $null
    $null | docker rm -f mcp-ssh-server mcp-ssh-direct mcp-ssh-proxy-bridge mcp-ssh-proxy-client mcp-local-mock mcp-bridge-server mcp-bridge-client 2> $null
}

try {
    switch ($Test) {
        "local-mock" {
            python test_local_mock.py
        }

        "start-bridge-sse" {
            python generate_local_config.py
            python -m mcp_stdio_bridge.main --config config.generated.yaml --transport sse --port 8000 --verbose
        }

        "test-sse" {
            python test_mcp_local_bridge.py --url $SseUrl $(if ($ApiKey) { "--api-key $ApiKey" })
        }

        "ssh" {
            python test_mcp_ssh_stdio.py --host $SshHost --config $RemoteConfig $(if ($SshArgs) { "--ssh-args ""$SshArgs""" })
        }

        "docker-local" {
            Write-Host "[*] Running Docker Local Mock..."
            Invoke-Docker @("up", "--build", "--abort-on-container-exit", "--exit-code-from", "local-mock", "local-mock")
        }

        "docker-sse" {
            Write-Host "[*] Running Docker SSE Pipeline..."
            Invoke-Docker @("up", "--build", "-d", "bridge")
            Invoke-Docker @("up", "--build", "--abort-on-container-exit", "--exit-code-from", "client", "bridge", "client")
        }

        "docker-ssh-direct" {
            Write-Host "[*] Running Docker SSH Direct..."
            Invoke-Docker @("up", "--build", "-d", "ssh-server")
            Invoke-Docker @("up", "--build", "--abort-on-container-exit", "--exit-code-from", "ssh-direct-test", "ssh-server", "ssh-direct-test")
        }

        "docker-ssh-proxy" {
            Write-Host "[*] Running Docker SSH Proxy (Forcing Clean Build)..."
            Invoke-Docker @("build", "--no-cache")
            Invoke-Docker @("up", "--force-recreate", "--abort-on-container-exit", "--exit-code-from", "ssh-proxy-client", "ssh-server", "ssh-proxy-bridge", "ssh-proxy-client")
        }
    }
} finally {
    if ($IsDockerTest) {
        Write-Host "[*] Cleaning up Docker resources..."
        $null | docker compose -p $Project -f $Yaml down -v --timeout 0 --remove-orphans
    }
    Pop-Location
}
