# Ollama LAN TLS endpoint on macOS

Adds a publicly trusted HTTPS endpoint in front of the existing local Ollama listener without replacing or changing Ollama itself.

## Topology

```text
ollama-lan.anit.guru:11435 (10.0.10.210, TLS)
  -> Caddy LaunchAgent on this Mac
  -> http://127.0.0.1:11434 (Ollama)
```

The exact Bunny DNS `A` record overrides the public wildcard/front-door record and points directly to the Mac's private LAN address. Traffic remains on the LAN after DNS resolution. Caddy uses Bunny DNS-01 only to obtain and renew a publicly trusted certificate.

## Security and secrets

- Ollama's original `http://<mac>:11434` listener is unchanged.
- Caddy binds only to `10.0.10.210:11435`.
- The Bunny API key remains in the SOPS store and is loaded by `~/.local/bin/secret bunny API_KEY` when the LaunchAgent starts.
- No API key is committed to this repository or written to the LaunchAgent plist.
- This adds transport encryption, not Ollama application authentication. The existing Ollama listener is already reachable on the LAN.

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
curl -fsS https://ollama-lan.anit.guru:11435/api/version
curl -fsS https://ollama-lan.anit.guru:11435/v1/models
launchctl print gui/$UID/com.anitguru.ollama-tls
```

Expected client base URL:

```text
https://ollama-lan.anit.guru:11435/v1
```

If a managed work VPN filters public DNS responses containing private addresses, add this hosts entry on that client:

```text
10.0.10.210 ollama-lan.anit.guru
```

The hostname must remain `ollama-lan.anit.guru` so it matches the certificate.
