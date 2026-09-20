"""Domain rules, independent of FastAPI and of the database.

Everything here is a plain function or dataclass over plain values. That is deliberate: the rules
about what makes a trip valid, and which status may follow which, are the part of this service most
worth testing without a request, a session or a container in the way.
"""
