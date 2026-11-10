// SPDX-License-Identifier: GPL-2.0-or-later
// Headless HLE thread lifecycle smoke test. No copyrighted game assets required.
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdio>
#include <mutex>
#include <stop_token>
#include <thread>

#include "core/libraries/kernel/threads.h"

// HLE test processes have no guest TLS. The production game provides this.
extern "C" void runtime_thread_attach_host(const char*) {}

using Libraries::Kernel::Thread;
using namespace std::chrono_literals;

int main() {
    // Test natural EOF: two decoder callbacks wake with empty packet queues.
    // The demuxer waits on completion flags; only the owning thread Stop()s.
    {
        std::mutex mutex;
        std::condition_variable_any ready;
        std::atomic<bool> eof{false};
        std::atomic<int> completed{0};
        Thread video, audio, demux;

        auto decode = [&](std::stop_token stop) {
            std::unique_lock lock(mutex);
            const bool end = ready.wait(lock, stop, [&] {
                return eof.load(std::memory_order_acquire);
            });
            if (end) completed.fetch_add(1, std::memory_order_relaxed);
        };

        video.Run(decode);
        audio.Run(decode);
        demux.Run([&](std::stop_token) {
            eof.store(true, std::memory_order_release);
            ready.notify_all();
            video.WaitForFinished();
            audio.WaitForFinished();
        });
        demux.WaitForFinished();
        if (completed.load() != 2) {
            std::fprintf(stderr, "HLE smoke: EOF did not wake both decoders\n");
            return 1;
        }

        video.Stop();
        audio.Stop();
        demux.Stop();
        // Repeated cleanup must be harmless and no longer join anything.
        video.Stop();
        audio.Stop();
        demux.Stop();
    }

    // Test mid-playback stop: request stop on every decoder before joining,
    // and notify the queues so stop-token waits can terminate promptly.
    {
        std::mutex mutex;
        std::condition_variable_any queue;
        std::atomic<int> exited{0};
        Thread video, audio;
        const auto parked = [&](std::stop_token stop) {
            std::unique_lock lock(mutex);
            queue.wait(lock, stop, [] { return false; });
            exited.fetch_add(1, std::memory_order_release);
        };
        video.Run(parked);
        audio.Run(parked);
        video.RequestStop();
        audio.RequestStop();
        queue.notify_all();
        video.Stop();
        audio.Stop();
        if (exited.load(std::memory_order_acquire) != 2) {
            std::fprintf(stderr, "HLE smoke: workers survived Stop()\n");
            return 2;
        }
    }

    // Test restarting the same thread wrapper after Stop().
    {
        Thread worker;
        std::atomic<int> count{0};
        for (int i = 0; i < 4; ++i) {
            worker.Run([&](std::stop_token) {
                count.fetch_add(1, std::memory_order_release);
            });
            worker.WaitForFinished();
            worker.Stop();
        }
        if (count.load(std::memory_order_acquire) != 4) {
            std::fprintf(stderr, "HLE smoke: worker restart lost completion\n");
            return 3;
        }
    }

    std::puts("HLE thread lifecycle smoke ok");
    return 0;
}
