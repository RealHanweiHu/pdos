"""Human accounts and sign-in (D214, with D86/D192 under P78).

- ``passwords``: scrypt hashing (standard library only) and the password rules.
- ``sign_in``: steps before a tenant is known; runs on the auth role through the
  database functions of migration s0_0856.
- ``management``: administrator actions inside one tenant transaction.
- ``api``: HTTP routes. The browser never sees a session token: the web BFF keeps it
  in an HttpOnly cookie.

"Owner" in P78 maps to an active human tenant administrator; pdos-next has a single
administrator tier.
"""
