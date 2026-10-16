"""Built-in fx_channel frontends.

User-facing and operator-facing frontends live in separate packages:

- fx_channel.frontends.user
- fx_channel.frontends.operator

They use different application-port contracts and must not import each other.
"""
