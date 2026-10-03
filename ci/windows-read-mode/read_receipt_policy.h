// SPDX-License-Identifier: MIT
#pragma once

#include <cstdint>
#include <optional>
#include <utility>

namespace Capy {

// Owned by one MTP::Instance, accessed on its owning/UI thread. A permission is
// bound to an already allocated request id AND its TL constructor, never to
// "the next request". Suppressed work is completed locally, never replayed.
class ReadReceiptPolicy final {
public:

	void setSilent(bool silent) {
		_silent = silent;
		_explicit.reset();
	}
	[[nodiscard]] bool silent() const { return _silent; }
	void reset() { setSilent(false); }
	void allow(std::int64_t request, std::uint32_t constructor) {
		_explicit = std::make_pair(request, constructor);
	}
	[[nodiscard]] bool suppress(std::int64_t request,
			std::uint32_t constructor, bool isRead) {
		const auto permitted = _explicit
			&& *_explicit == std::make_pair(request, constructor);
		if (_explicit && _explicit->first == request) _explicit.reset();
		return isRead && _silent && !permitted;
	}

private:
	bool _silent = false;
	std::optional<std::pair<std::int64_t, std::uint32_t>> _explicit;

};

} // namespace Capy
