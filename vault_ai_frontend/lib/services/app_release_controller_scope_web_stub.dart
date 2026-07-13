/// Non-web stub — visibility change hooks are a no-op on mobile /
/// desktop. Returns null so callers know there's nothing to detach.

typedef _CheckForUpdate = void Function();

void Function()? attachVisibilityChange(_CheckForUpdate cb) => null;
