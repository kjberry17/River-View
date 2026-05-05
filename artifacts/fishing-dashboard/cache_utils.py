import time as _time
import threading

_CACHE = {}
_LOCK = threading.Lock()


def ttl_cache(ttl: int = 300):
    def decorator(fn):
        key = fn.__qualname__

        def wrapper(*args, **kwargs):
            cache_key = key + str(args) + str(sorted(kwargs.items()))
            with _LOCK:
                if cache_key in _CACHE:
                    val, ts = _CACHE[cache_key]
                    if _time.time() - ts < ttl:
                        return val
            result = fn(*args, **kwargs)
            with _LOCK:
                _CACHE[cache_key] = (result, _time.time())
            return result

        def clear():
            prefix = key
            with _LOCK:
                for k in list(_CACHE.keys()):
                    if k.startswith(prefix):
                        del _CACHE[k]

        wrapper.clear = clear
        wrapper.__name__ = fn.__name__
        wrapper.__qualname__ = fn.__qualname__
        return wrapper

    return decorator
