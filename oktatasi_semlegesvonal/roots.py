# -*- coding: utf-8 -*-
"""Find all terrain/level intersections on one fixed-radius circle."""
from __future__ import annotations

from math import atan2, cos, degrees, hypot, pi, sin


TAU = 2.0 * pi


def _f(sample, cx, cy, radius, theta, required_z):
    z = sample(cx + radius * cos(theta), cy + radius * sin(theta))
    return None if z is None else z - required_z


def _bisect(sample, cx, cy, radius, required_z, left, right, fl, fr, z_tol=1e-6):
    if abs(fl) <= z_tol:
        return left
    if abs(fr) <= z_tol:
        return right
    for _ in range(64):
        mid = 0.5 * (left + right)
        fm = _f(sample, cx, cy, radius, mid, required_z)
        if fm is None:
            return None
        if abs(fm) <= z_tol or (right - left) * radius <= 1e-5:
            return mid
        if fl * fm <= 0:
            right, fr = mid, fm
        else:
            left, fl = mid, fm
    return 0.5 * (left + right)


def _tangent_minimum(sample, cx, cy, radius, required_z, left, right):
    """Golden-section minimisation of |F|, to keep tangential intersections."""
    phi = (5**0.5 - 1.0) / 2.0
    a, b = left, right
    x1, x2 = b - phi * (b-a), a + phi * (b-a)
    f1 = _f(sample, cx, cy, radius, x1, required_z)
    f2 = _f(sample, cx, cy, radius, x2, required_z)
    if f1 is None or f2 is None:
        return None
    for _ in range(48):
        if abs(f1) <= abs(f2):
            b, x2, f2 = x2, x1, f1
            x1 = b - phi * (b-a)
            f1 = _f(sample, cx, cy, radius, x1, required_z)
            if f1 is None: return None
        else:
            a, x1, f1 = x1, x2, f2
            x2 = a + phi * (b-a)
            f2 = _f(sample, cx, cy, radius, x2, required_z)
            if f2 is None: return None
    theta = x1 if abs(f1) <= abs(f2) else x2
    value = _f(sample, cx, cy, radius, theta, required_z)
    return theta if value is not None and abs(value) <= 1e-6 else None


def find_circle_roots(sample, cx, cy, radius, required_z, sample_deg=1.0):
    """Return all distinct (x, y, z, heading-degrees) circle intersections.

    The 1° discovery mesh is only used to bracket roots; every reported point
    is subsequently refined against the B-spline terrain surface.
    """
    count = max(36, int(round(360.0 / sample_deg)))
    angles = [TAU * i / count for i in range(count + 1)]
    values = [_f(sample, cx, cy, radius, a, required_z) for a in angles]
    roots = []
    for i in range(count):
        a, b, fa, fb = angles[i], angles[i+1], values[i], values[i+1]
        if fa is None or fb is None:
            continue
        if abs(fa) <= 1e-6:
            roots.append(a)
        if fa * fb < 0:
            root = _bisect(sample, cx, cy, radius, required_z, a, b, fa, fb)
            if root is not None: roots.append(root)
    # An exactly tangent level may not change sign. Check sampled local minima.
    for i in range(1, count):
        prev, current, nxt = values[i-1], values[i], values[i+1]
        if None not in (prev, current, nxt) and abs(current) <= abs(prev) and abs(current) <= abs(nxt):
            root = _tangent_minimum(sample, cx, cy, radius, required_z, angles[i-1], angles[i+1])
            if root is not None: roots.append(root)
    unique = []
    angle_tol = 1e-5 / max(radius, 1e-9)
    for theta in sorted((r % TAU for r in roots)):
        if not any(abs((theta - old + pi) % TAU - pi) <= angle_tol for old in unique):
            unique.append(theta)
    result = []
    for theta in unique:
        x, y = cx + radius*cos(theta), cy + radius*sin(theta)
        z = sample(x, y)
        if z is not None and abs(z - required_z) <= 5e-6:
            result.append((x, y, z, (degrees(theta) + 360.0) % 360.0))
    return result


def heading_degrees(a, b):
    return (degrees(atan2(b[1] - a[1], b[0] - a[0])) + 360.0) % 360.0


def distance(a, b):
    return hypot(b[0] - a[0], b[1] - a[1])
