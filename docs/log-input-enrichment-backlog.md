# Log input and type enrichment backlog

DeepParse is the version-pinned syntactic front end for clustering and initial
typed templates. ASIM schema names and field roles must not feed back into that
clustering decision: a physical value such as an IP address does not establish
whether it is a source, destination, actor, target, or reporting device.

The default path therefore remains:

```text
raw events -> DeepParse -> stable clusters and coarse slots -> semantic mapping
```

Future input support can be added at two target-neutral boundaries.

## Input framing and structure adapters

These adapters would preserve source structure before line-oriented clustering:

- JSON and JSONL, including nested application and cloud-audit records;
- CEF and LEEF extension key/value fields;
- RFC 3164/RFC 5424 syslog headers;
- common key/value and logfmt records;
- Java, .NET, Python, and other multiline exception or stack-trace events;
- Windows Event and registry-oriented records;
- common web/application logger prefixes and continuation lines.

An adapter must retain the original event, parsed boundaries, and provenance. It
must not silently flatten multiple records or treat ASIM target fields as source
truth.

## Post-clustering slot evidence

A separate profiler may attach scored, target-neutral evidence using all examples
for a slot. Candidate shapes include IPv6, CIDR, Windows SID, cryptographic hash,
Windows/UNC/registry path, richer timestamps, FQDN, alternate MAC, URI, and a
decomposable address/port endpoint.

Start these as post-clustering evidence so they cannot change cluster membership.
Promote a pattern into the DeepParse mask layer only when an ablation shows that
its absence repeatedly fragments coherent clusters and that the proposed mask does
not overmerge distinct templates. Prefer a reviewed upstream DeepParse contribution
over a permanent local fork.

Broad masks for ports, PIDs, usernames, hostnames, actions, and outcomes are
deliberately excluded: their syntax is ambiguous and their meaning belongs in the
semantic-frame, lexical, and retrieval approaches.
