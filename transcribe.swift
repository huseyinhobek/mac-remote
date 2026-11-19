// transcribe <audio-file> [locale]: print the speech in the file as text.
// Uses macOS's on-device dictation model (macOS 26+): no network, no API key, no permission prompt.
import AVFoundation
import Foundation
import Speech

@main struct Transcribe {
    static func fail(_ message: String) -> Never {
        FileHandle.standardError.write((message + "\n").data(using: .utf8)!)
        exit(1)
    }

    static func main() async {
        let args = CommandLine.arguments
        guard args.count >= 2 else { fail("usage: transcribe <audio-file> [locale]") }
        let locale = args.count > 2 && !args[2].isEmpty ? Locale(identifier: args[2]) : Locale.current
        let wanted = locale.identifier(.bcp47)
        guard await DictationTranscriber.supportedLocales.contains(where: { $0.identifier(.bcp47) == wanted }) else {
            fail("speech recognition doesn't support \(wanted)")
        }
        do {
            let transcriber = DictationTranscriber(locale: locale, contentHints: [], transcriptionOptions: [.punctuation],
                                                   reportingOptions: [], attributeOptions: [])
            // First use of a language downloads its on-device model once.
            if let install = try await AssetInventory.assetInstallationRequest(supporting: [transcriber]) {
                try await install.downloadAndInstall()
            }
            let analyzer = SpeechAnalyzer(modules: [transcriber])
            let file = try AVAudioFile(forReading: URL(fileURLWithPath: args[1]))
            async let text = transcriber.results.reduce("") { $0 + String($1.text.characters) }
            if let end = try await analyzer.analyzeSequence(from: file) {
                try await analyzer.finalizeAndFinish(through: end)
            } else {
                await analyzer.cancelAndFinishNow()
            }
            print(try await text.trimmingCharacters(in: .whitespacesAndNewlines))
        } catch {
            fail(error.localizedDescription)
        }
    }
}
