import AppKit
import AVFoundation
import Foundation
import Speech

var outputHandle = FileHandle.standardOutput

func emit(_ payload: [String: Any]) {
    guard let data = try? JSONSerialization.data(withJSONObject: payload),
          var line = String(data: data, encoding: .utf8) else { return }
    line.append("\n")
    outputHandle.write(Data(line.utf8))
}

func log(_ message: String) {
    let line = "harness-stt: \(message)\n"
    FileHandle.standardError.write(Data(line.utf8))
}

func parseSocketPath() -> String? {
    let args = Array(CommandLine.arguments.dropFirst())
    if let index = args.firstIndex(of: "--socket"), index + 1 < args.count {
        return args[index + 1]
    }
    return nil
}

func connectUnixSocket(_ path: String) -> FileHandle? {
    let fd = Darwin.socket(AF_UNIX, SOCK_STREAM, 0)
    guard fd >= 0 else { return nil }
    var addr = sockaddr_un()
    addr.sun_family = sa_family_t(AF_UNIX)
    let maxPath = MemoryLayout.size(ofValue: addr.sun_path)
    guard path.utf8.count + 1 <= maxPath else {
        Darwin.close(fd)
        return nil
    }
    withUnsafeMutablePointer(to: &addr.sun_path) { ptr in
        ptr.withMemoryRebound(to: CChar.self, capacity: maxPath) { dst in
            path.withCString { src in
                _ = strncpy(dst, src, maxPath)
            }
        }
    }
    let ok = withUnsafePointer(to: &addr) { ptr in
        ptr.withMemoryRebound(to: sockaddr.self, capacity: 1) { sockPtr in
            Darwin.connect(fd, sockPtr, socklen_t(MemoryLayout<sockaddr_un>.size))
        }
    }
    guard ok == 0 else {
        Darwin.close(fd)
        return nil
    }
    return FileHandle(fileDescriptor: fd, closeOnDealloc: true)
}

func connectUnixSocketRetry(_ path: String, attempts: Int = 50) -> FileHandle? {
    for _ in 0..<attempts {
        if let handle = connectUnixSocket(path) {
            return handle
        }
        usleep(100_000)
    }
    return nil
}

final class Transcriber {
    private let recognizer: SFSpeechRecognizer
    private let audioEngine = AVAudioEngine()
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?
    private var stopping = false
    private var tapInstalled = false

    private var lastHypothesis = ""

    var supportsOnDevice: Bool { recognizer.supportsOnDeviceRecognition }

    init?(locale: Locale = .current) {
        guard let recognizer = SFSpeechRecognizer(locale: locale) else { return nil }
        self.recognizer = recognizer
    }

    func start() throws {
        guard recognizer.isAvailable else {
            throw NSError(
                domain: "harness-stt",
                code: 1,
                userInfo: [NSLocalizedDescriptionKey: "Speech recognizer is not available for this locale."]
            )
        }

        let inputNode = audioEngine.inputNode
        let format = inputNode.inputFormat(forBus: 0)
        guard format.sampleRate > 0, format.channelCount > 0 else {
            throw NSError(
                domain: "harness-stt",
                code: 2,
                userInfo: [NSLocalizedDescriptionKey: "No usable microphone input format."]
            )
        }

        if !tapInstalled {
            inputNode.installTap(onBus: 0, bufferSize: 1024, format: format) { [weak self] buffer, _ in
                self?.request?.append(buffer)
            }
            tapInstalled = true
        }

        audioEngine.prepare()
        try audioEngine.start()
        startRequest(cancelCurrent: false)
        emit(["type": "ready", "pid": ProcessInfo.processInfo.processIdentifier])
    }

    func stop() {
        stopping = true
        flushHypothesis()
        task?.cancel()
        task = nil
        request?.endAudio()
        request = nil
        if tapInstalled {
            audioEngine.inputNode.removeTap(onBus: 0)
            tapInstalled = false
        }
        if audioEngine.isRunning {
            audioEngine.stop()
        }
    }

    private func startRequest(cancelCurrent: Bool) {
        guard !stopping else { return }

        if cancelCurrent {
            flushHypothesis()
            task?.cancel()
        }
        task = nil
        request?.endAudio()

        let request = SFSpeechAudioBufferRecognitionRequest()
        request.shouldReportPartialResults = true
        request.taskHint = .dictation
        if #available(macOS 13.0, *) {
            request.addsPunctuation = true
        }
        if recognizer.supportsOnDeviceRecognition {
            request.requiresOnDeviceRecognition = true
        }
        self.request = request

        task = recognizer.recognitionTask(with: request) { [weak self] result, error in
            guard let self, !self.stopping else { return }
            if let result {
                self.emitHypothesis(result.bestTranscription.formattedString, isFinal: result.isFinal)
                if result.isFinal {
                    DispatchQueue.main.async { self.startRequest(cancelCurrent: false) }
                    return
                }
            }
            if let error {
                if self.isCancellation(error) { return }
                log("recognition restart: \(error.localizedDescription)")
                DispatchQueue.main.async { self.startRequest(cancelCurrent: true) }
            }
        }
    }

    private func emitHypothesis(_ raw: String, isFinal: Bool) {
        let text = Self.normalize(raw)
        guard !text.isEmpty else { return }
        if !isFinal, !lastHypothesis.isEmpty, !Self.isSameUtterance(lastHypothesis, text) {
            emit(["type": "final", "text": lastHypothesis])
        }
        emit(["type": isFinal ? "final" : "partial", "text": text])
        lastHypothesis = isFinal ? "" : text
    }

    private func flushHypothesis() {
        if !lastHypothesis.isEmpty {
            emit(["type": "final", "text": lastHypothesis])
            lastHypothesis = ""
        }
    }

    private static func normalize(_ text: String) -> String {
        text.split { $0.isNewline || $0.isWhitespace }.joined(separator: " ")
    }

    private static func isSameUtterance(_ old: String, _ new: String) -> Bool {
        if old.isEmpty || new.isEmpty { return true }
        if new.hasPrefix(old) { return true }
        let oldWords = old.split(separator: " ")
        let newWords = new.split(separator: " ")
        if old.hasPrefix(new) && newWords.count >= max(1, oldWords.count - 2) {
            return true
        }
        var common = 0
        for (left, right) in zip(oldWords, newWords) {
            if left.lowercased() != right.lowercased() { break }
            common += 1
        }
        if common >= 2 { return true }
        return false
    }

    private func isCancellation(_ error: Error) -> Bool {
        let nsError = error as NSError
        if nsError.domain == NSURLErrorDomain && nsError.code == NSURLErrorCancelled {
            return true
        }
        let description = nsError.localizedDescription.lowercased()
        if description.contains("cancel") { return true }
        if nsError.domain == "kAFAssistantErrorDomain" && [203, 209, 216, 1110, 1700].contains(nsError.code) {
            return nsError.code == 203 || nsError.code == 216
        }
        return false
    }
}

func requestPermissions(_ completion: @escaping (String?) -> Void) {
    SFSpeechRecognizer.requestAuthorization { status in
        DispatchQueue.main.async {
            guard status == .authorized else {
                completion(
                    "Speech recognition not authorized. Enable it in System Settings > Privacy & Security > Speech Recognition."
                )
                return
            }
            AVCaptureDevice.requestAccess(for: .audio) { granted in
                DispatchQueue.main.async {
                    if granted {
                        completion(nil)
                    } else {
                        completion(
                            "Microphone access denied. Enable it in System Settings > Privacy & Security > Microphone."
                        )
                    }
                }
            }
        }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    let transcriber: Transcriber

    init(transcriber: Transcriber) {
        self.transcriber = transcriber
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        requestPermissions { errorMessage in
            if let errorMessage {
                emit(["type": "error", "message": errorMessage])
                NSApp.terminate(nil)
                return
            }
            do {
                try self.transcriber.start()
            } catch {
                emit(["type": "error", "message": error.localizedDescription])
                NSApp.terminate(nil)
            }
        }
    }
}

if let socketPath = parseSocketPath() {
    guard let handle = connectUnixSocketRetry(socketPath) else {
        log("could not connect to socket \(socketPath)")
        exit(1)
    }
    outputHandle = handle
}

signal(SIGINT, SIG_IGN)
signal(SIGTERM, SIG_IGN)

guard let transcriber = Transcriber() else {
    emit(["type": "error", "message": "Speech recognizer is unavailable for the current locale."])
    exit(1)
}

if transcriber.supportsOnDevice {
    log("on-device recognition available")
} else {
    log("on-device recognition unavailable; using default recognizer")
}

func shutdown() {
    transcriber.stop()
    exit(0)
}

let sigterm = DispatchSource.makeSignalSource(signal: SIGTERM, queue: .main)
sigterm.setEventHandler { shutdown() }
sigterm.resume()

let sigint = DispatchSource.makeSignalSource(signal: SIGINT, queue: .main)
sigint.setEventHandler { shutdown() }
sigint.resume()

let app = NSApplication.shared
app.setActivationPolicy(.accessory)
let delegate = AppDelegate(transcriber: transcriber)
app.delegate = delegate
app.run()
