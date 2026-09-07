// midimon: print every MIDI message the Mac receives, from every source,
// including sources that appear after it starts (such as the synth being
// plugged in or reset). Used for bring-up: does the Seed enumerate, do notes
// arrive, are they the numbers we expect.
//
//   make tools/midimon            build (needs the Xcode command line tools)
//   tools/midimon [seconds]       listen for that long (default 60)
//
import CoreMIDI
import Foundation

let f = DateFormatter()
f.dateFormat = "HH:mm:ss.SSS"
let secs = Double(CommandLine.arguments.dropFirst().first ?? "60") ?? 60
let noteNames = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

func name(_ obj: MIDIObjectRef) -> String {
    var s: Unmanaged<CFString>?
    MIDIObjectGetStringProperty(obj, kMIDIPropertyDisplayName, &s)
    return (s?.takeRetainedValue() as String?) ?? "?"
}

func noteName(_ n: UInt8) -> String {
    return "\(noteNames[Int(n) % 12])\(Int(n) / 12 - 1)"
}

func decode(_ b: [UInt8]) -> String {
    guard let st = b.first else { return "" }
    if st == 0xF0 {
        let body = b.dropFirst().filter { $0 != 0xF7 }
        let text = String(bytes: body.map { $0 < 0x20 || $0 > 0x7e ? 0x2e : $0 }, encoding: .ascii) ?? ""
        return "sysex \"\(text)\""
    }
    let ch = Int(st & 0x0F) + 1
    switch st & 0xF0 {
    case 0x90 where b.count >= 3 && b[2] > 0:
        return "note on  ch\(ch) \(noteName(b[1])) (\(b[1])) vel \(b[2])"
    case 0x80, 0x90:
        return b.count >= 2 ? "note off ch\(ch) \(noteName(b[1])) (\(b[1]))" : ""
    case 0xB0 where b.count >= 3:
        return "cc ch\(ch) \(b[1]) = \(b[2])"
    case 0xC0 where b.count >= 2:
        return "program ch\(ch) \(b[1])"
    case 0xE0 where b.count >= 3:
        return "pitch bend ch\(ch) \(Int(b[2]) * 128 + Int(b[1]) - 8192)"
    default:
        return ""
    }
}

// Split a packet into individual MIDI messages; packets often carry several.
func messages(_ bytes: [UInt8]) -> [[UInt8]] {
    var out: [[UInt8]] = []
    var i = 0
    while i < bytes.count {
        let st = bytes[i]
        var len = 1
        switch st & 0xF0 {
        case 0x80, 0x90, 0xA0, 0xB0, 0xE0: len = 3
        case 0xC0, 0xD0: len = 2
        case 0xF0:
            if st == 0xF0 {
                var j = i + 1
                while j < bytes.count && bytes[j] != 0xF7 { j += 1 }
                len = min(j + 1, bytes.count) - i
            } else if st == 0xF1 || st == 0xF3 {
                len = 2
            } else if st == 0xF2 {
                len = 3
            }
        default: len = 1 // stray data byte: emit alone
        }
        out.append(Array(bytes[i..<min(i + len, bytes.count)]))
        i += len
    }
    return out
}

var client = MIDIClientRef()
var port = MIDIPortRef()
var connected = Set<MIDIObjectRef>()

func connectAll() {
    for i in 0..<MIDIGetNumberOfSources() {
        let s = MIDIGetSource(i)
        if connected.contains(s) { continue }
        MIDIPortConnectSource(port, s, UnsafeMutableRawPointer(bitPattern: Int(s)))
        connected.insert(s)
        print("\(f.string(from: Date())) listening to [\(name(s))]")
        fflush(stdout)
    }
}

MIDIClientCreateWithBlock("midimon" as CFString, &client) { note in
    let id = note.pointee.messageID
    if id == .msgObjectAdded || id == .msgSetupChanged { connectAll() }
}
MIDIInputPortCreateWithBlock(client, "in" as CFString, &port) { pktList, srcRefCon in
    let src = MIDIObjectRef(UInt32(truncatingIfNeeded: Int(bitPattern: srcRefCon)))
    let count = Int(pktList.pointee.numPackets)
    let packetOffset = MemoryLayout<MIDIPacketList>.offset(of: \MIDIPacketList.packet)!
    let dataOffset = MemoryLayout<MIDIPacket>.offset(of: \MIDIPacket.data)!
    var ptr = UnsafeRawPointer(pktList).advanced(by: packetOffset).assumingMemoryBound(to: MIDIPacket.self)
    for _ in 0..<count {
        let n = Int(ptr.pointee.length)
        let bytes = Array(UnsafeRawBufferPointer(start: UnsafeRawPointer(ptr).advanced(by: dataOffset), count: n))
        for m in messages(bytes) {
            let hex = m.map { String(format: "%02X", $0) }.joined(separator: " ")
            print("\(f.string(from: Date())) [\(name(src))] \(hex)  \(decode(m))")
        }
        fflush(stdout)
        ptr = UnsafePointer(MIDIPacketNext(ptr))
    }
}

print("midimon: \(MIDIGetNumberOfSources()) source(s) now; new ones are picked up automatically; \(Int(secs)) s")
connectAll()
fflush(stdout)
RunLoop.main.run(until: Date(timeIntervalSinceNow: secs))
print("midimon: done")
