// SPDX-License-Identifier: MIT
#pragma once
#include "capybara/archive_store.h"
class HistoryItem;
namespace Capy {
// UI thread only, called before native item/cache mutation. Does not download.
bool CaptureArchive(not_null<HistoryItem*> item, Archive::Reason reason);
} // namespace Capy
