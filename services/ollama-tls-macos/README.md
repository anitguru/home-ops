# Ollama LAN TLS endpoint on macOS

Adds a publicly trusted HTTPS endpoint in front of the existing local Ollama listener without replacing or changing Ollama itself.

## Topology

```text
ollama-lan.anit.guru:11435 (10.0.10.210 or 10.0.10.217, TLS)
  -> Caddy LaunchAgent on this Mac
  -> http://127.0.0.1:11434 (Ollama)
```

The exact Bunny DNS `A` record overrides the public wildcard/front-door record and points directly to the Mac's private LAN address. Traffic remains on the LAN after DNS resolution. Caddy uses Bunny DNS-01 only to obtain and renew a publicly trusted certificate.

## Security and secrets

- Ollama's original `http://<mac>:11434` listener is unchanged.
- Caddy listens on IPv4 port `11435` so the service survives Wi-Fi/Ethernet interface changes, then enforces a source ACL allowing only loopback health checks and the work Mac's two reserved VLAN 60 addresses (`10.0.60.205` and `10.0.60.207`). PR60X limits the routed destinations to this Mac's `10.0.10.210` and `10.0.10.217` addresses.
- The Bunny API key remains in the SOPS store and is loaded by `~/.local/bin/secret bunny API_KEY` when the LaunchAgent starts.
- The HTTPS Bearer token remains under `ollama.M5_TLS_API_KEY` in SOPS and is loaded only when the LaunchAgent starts.
- No API key is committed to this repository or written to the LaunchAgent plist. Caddy removes the `Authorization` header before proxying to Ollama.
- This adds transport encryption and Bearer-token authentication on port `11435`. The existing unauthenticated Ollama listener on port `11434` is unchanged.
- PR60X rules permit only TCP `11435` from the work Mac's reserved Wi-Fi and Ethernet addresses (`10.0.60.205` and `10.0.60.207`) to this Mac's two VLAN 10 addresses (`10.0.10.210` and `10.0.10.217`). Direct `11434` is not exposed through those inter-VLAN rules. Local apps continue using `127.0.0.1:11434`.

| Work Mac source | M5 destination | Allowed service |
|---|---|---|
| `10.0.60.205` (Wi-Fi) | `10.0.10.210` (Wi-Fi) | TCP `11435` |
| `10.0.60.205` (Wi-Fi) | `10.0.10.217` (Ethernet) | TCP `11435` |
| `10.0.60.207` (Ethernet) | `10.0.10.210` (Wi-Fi) | TCP `11435` |
| `10.0.60.207` (Ethernet) | `10.0.10.217` (Ethernet) | TCP `11435` |

## Pinned build

- Caddy `v2.11.4`
- xcaddy `v0.4.5`
- `github.com/caddy-dns/bunny` `v1.2.0`

## Install or rebuild

```bash
brew install go
./install.sh
```

The custom binary, deployed Caddyfile/runner, and certificate state live under:

```text
~/Library/Application Support/ollama-tls-caddy/
```

The runtime files are copied there because macOS privacy controls can block
LaunchAgents from executing files directly under `~/Documents`.

The LaunchAgent is:

```text
~/Library/LaunchAgents/com.anitguru.ollama-tls.plist
```

## Verify

```bash
dig +short A ollama-lan.anit.guru @1.1.1.1
# Local health checks use loopback because Caddy rejects non-work LAN sources.
curl -sS --resolve ollama-lan.anit.guru:11435:127.0.0.1 -o /dev/null -w '%{http_code}\n' https://ollama-lan.anit.guru:11435/api/version # expect 401
M5_TLS_API_KEY="$(~/.local/bin/secret ollama M5_TLS_API_KEY)"
curl -fsS --resolve ollama-lan.anit.guru:11435:127.0.0.1 -H "Authorization: Bearer $M5_TLS_API_KEY" https://ollama-lan.anit.guru:11435/api/version
curl -fsS --resolve ollama-lan.anit.guru:11435:127.0.0.1 -H "Authorization: Bearer $M5_TLS_API_KEY" https://ollama-lan.anit.guru:11435/v1/models
unset M5_TLS_API_KEY
launchctl print gui/$UID/com.anitguru.ollama-tls
```

Expected client base URL:

```text
https://ollama-lan.anit.guru:11435/v1
```

Configure the client API-key field with the value from `ollama.M5_TLS_API_KEY`.
OpenAI-compatible clients send it as `Authorization: Bearer $M5_TLS_API_KEY`.

If a managed work VPN filters public DNS responses containing private addresses, add this hosts entry on that client:

```text
10.0.10.210 ollama-lan.anit.guru
# Or, while testing the Ethernet path:
10.0.10.217 ollama-lan.anit.guru
```

The hostname must remain `ollama-lan.anit.guru` so it matches the certificate.
