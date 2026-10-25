import AppKit
import AVFoundation
import Carbon.HIToolbox
import Network
import Speech

/// "El oído" de Spotify Voice DJ: app de barra de menús, siempre activa y ligera.
/// Se activa con "Hey Jarvis" (detector en el cerebro) o con ⌥Espacio, escucha la
/// petición, la transcribe en el propio Mac (sin internet), se la pasa al cerebro
/// (127.0.0.1:8765) y lee la respuesta en voz alta.
@main
final class OidoApp: NSObject, NSApplicationDelegate, AVSpeechSynthesizerDelegate {
    static func main() {
        let app = NSApplication.shared
        let delegado = OidoApp()
        app.delegate = delegado
        app.setActivationPolicy(.accessory)
        app.run()
    }

    private var item: NSStatusItem!
    private var config = Config.cargar()
    private var itemEscucha: NSMenuItem!
    private lazy var micro = Microfono(enviarAlDespertador: config.activacionPorVoz)
    private let voz = AVSpeechSynthesizer()
    private let vigilante = Vigilante()
    private var ocupado = false
    private var seguimientoPendiente = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        reposo()
        let menu = NSMenu()
        menu.addItem(NSMenuItem(title: "Hablar (⌥Espacio)", action: #selector(atajo), keyEquivalent: ""))
        itemEscucha = NSMenuItem(title: "Escuchar «Hey Jarvis» (⌥⇧Espacio)", action: #selector(alternarEscucha), keyEquivalent: "")
        itemEscucha.state = config.activacionPorVoz ? .on : .off
        menu.addItem(itemEscucha)
        menu.addItem(.separator())
        menu.addItem(NSMenuItem(title: "Salir", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q"))
        item.menu = menu
        voz.delegate = self
        Atajo.registrar(id: 1, modificadores: optionKey) { [weak self] in self?.atajo() }
        Atajo.registrar(id: 2, modificadores: optionKey | shiftKey) { [weak self] in self?.alternarEscucha() }
        micro.alActivarse = { [weak self] in self?.escuchar(porVoz: true) }
        micro.pedirPermisosYArrancar()
    }

    private func poner(_ simbolo: String, _ ayuda: String) {
        item.button?.image = NSImage(systemSymbolName: simbolo, accessibilityDescription: ayuda)
        item.button?.toolTip = ayuda
    }

    private func reposo() {
        if config.activacionPorVoz {
            poner("music.note", "DJ: di «Hey Jarvis» o pulsa ⌥Espacio")
        } else {
            poner("mic.slash", "DJ: escucha apagada · ⌥Espacio para hablar · ⌥⇧Espacio para activarla")
        }
    }

    /// Enciende o apaga la escucha continua. Apagada, el micrófono queda cerrado
    /// (sin punto naranja) y solo se abre al pulsar ⌥Espacio.
    @objc private func alternarEscucha() {
        config.activacionPorVoz.toggle()
        config.guardarActivacion()
        itemEscucha.state = config.activacionPorVoz ? .on : .off
        if config.activacionPorVoz {
            micro.activarEscucha()
            NSSound(named: "Morse")?.play()
        } else {
            micro.desactivarEscucha()
            NSSound(named: "Funk")?.play()
        }
        if !ocupado { reposo() }
    }

    /// El atajo empieza a escuchar; pulsarlo otra vez mientras escucha termina antes.
    @objc private func atajo() {
        if micro.capturando { micro.terminarCaptura(); return }
        escuchar(porVoz: false)
    }

    private func escuchar(porVoz: Bool, seguimiento: Bool = false) {
        guard !ocupado || seguimiento else { return }
        ocupado = true
        voz.stopSpeaking(at: .immediate)
        let volumen = Spotify.bajarVolumen()
        NSSound(named: seguimiento ? "Pop" : "Tink")?.play()
        poner("mic.fill", seguimiento ? "¿Algo más?" : "Escuchando…")
        micro.capturar(silencioInicial: seguimiento ? 4 : 5, usarPrevio: porVoz && !seguimiento) { [weak self] texto in
            Spotify.restaurarVolumen(volumen)
            self?.procesar(texto, eraSeguimiento: seguimiento)
        }
    }

    private func procesar(_ texto: String, eraSeguimiento: Bool) {
        let limpio = texto.trimmingCharacters(in: .whitespacesAndNewlines)
        if limpio.isEmpty || Self.esCancelacion(limpio) {
            if !eraSeguimiento && limpio.isEmpty { NSSound(named: "Bottle")?.play() }
            terminar()
            return
        }
        poner("ellipsis.circle", "Pensando: \(limpio)")
        Task {
            let respuesta = await Cerebro.pedir(limpio)
            await MainActor.run {
                self.seguimientoPendiente = self.config.seguimiento
                self.hablar(respuesta)
            }
        }
    }

    private static func esCancelacion(_ texto: String) -> Bool {
        let t = texto.lowercased()
        return ["olvídalo", "olvidalo", "nada", "cancela", "nada más", "eso es todo", "no gracias", "gracias"]
            .contains { t == $0 || t.hasPrefix($0 + " ") }
    }

    private func hablar(_ texto: String) {
        poner("speaker.wave.2.fill", texto)
        let frase = AVSpeechUtterance(string: texto)
        frase.voice = AVSpeechSynthesisVoice(language: config.voz)
        frase.rate = 0.52
        voz.speak(frase)
    }

    func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
        // Tras responder, unos segundos para pedir otra cosa sin repetir la frase de activación.
        if seguimientoPendiente {
            seguimientoPendiente = false
            escuchar(porVoz: true, seguimiento: true)
        } else {
            terminar()
        }
    }

    private func terminar() {
        ocupado = false
        reposo()
    }
}

// MARK: - Configuración (~/spotify-voice-dj/config.json)

struct Config {
    var activacionPorVoz = true
    var seguimiento = true
    var voz = "es-MX"

    private static var archivo: URL {
        FileManager.default.homeDirectoryForCurrentUser.appending(path: "spotify-voice-dj/config.json")
    }

    /// Guarda solo "activacion_por_voz" sin tocar el resto del archivo.
    func guardarActivacion() {
        var json = (try? Data(contentsOf: Self.archivo))
            .flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] } ?? [:]
        json["activacion_por_voz"] = activacionPorVoz
        if let datos = try? JSONSerialization.data(withJSONObject: json, options: [.prettyPrinted, .sortedKeys]) {
            try? datos.write(to: Self.archivo)
        }
    }

    static func cargar() -> Config {
        var c = Config()
        let url = FileManager.default.homeDirectoryForCurrentUser.appending(path: "spotify-voice-dj/config.json")
        if let datos = try? Data(contentsOf: url),
           let json = try? JSONSerialization.jsonObject(with: datos) as? [String: Any] {
            c.activacionPorVoz = json["activacion_por_voz"] as? Bool ?? true
            c.seguimiento = json["seguimiento"] as? Bool ?? true
            c.voz = json["voz"] as? String ?? "es-MX"
        }
        return c
    }
}

// MARK: - Micrófono: un solo motor de audio para el despertador y las peticiones

final class Microfono {
    var alActivarse: (() -> Void)?
    private(set) var capturando = false

    private var enviarAlDespertador: Bool
    private let motor = AVAudioEngine()
    private let reconocedor: SFSpeechRecognizer?
    private var peticion: SFSpeechAudioBufferRecognitionRequest?
    private var tarea: SFSpeechRecognitionTask?
    private var temporizador: Timer?
    private var texto = ""
    private var alTerminar: ((String) -> Void)?
    private var conexion: NWConnection?
    private var convertidor: AVAudioConverter?
    private let formato16k = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: 16000, channels: 1, interleaved: true)!

    // Búfer previo: los últimos ~2 s de audio, para que la petición no pierda su
    // comienzo ("Hey Jarvis, pon…" dicho de corrido) mientras arranca el reconocedor.
    private var previo: [AVAudioPCMBuffer] = []
    private let colaPrevio = DispatchQueue(label: "dj.previo")

    private func guardarPrevio(_ buffer: AVAudioPCMBuffer) {
        guard let copia = AVAudioPCMBuffer(pcmFormat: buffer.format, frameCapacity: buffer.frameLength) else { return }
        copia.frameLength = buffer.frameLength
        for canal in 0..<Int(buffer.format.channelCount) {
            if let origen = buffer.floatChannelData?[canal], let destino = copia.floatChannelData?[canal] {
                destino.update(from: origen, count: Int(buffer.frameLength))
            }
        }
        colaPrevio.sync {
            previo.append(copia)
            let limite = Int(2.0 * buffer.format.sampleRate / Double(max(buffer.frameLength, 1)))
            if previo.count > limite { previo.removeFirst(previo.count - limite) }
        }
    }

    private let silencio: TimeInterval = 1.4
    private let maximo: TimeInterval = 12

    init(enviarAlDespertador: Bool) {
        self.enviarAlDespertador = enviarAlDespertador
        let preferidos = ["es-CO", "es-419", "es-MX", "es-US", "es-ES"]
        reconocedor = preferidos.lazy
            .compactMap { SFSpeechRecognizer(locale: Locale(identifier: $0)) }
            .first { $0.supportsOnDeviceRecognition } ?? SFSpeechRecognizer(locale: Locale(identifier: "es-MX"))
    }

    func activarEscucha() {
        enviarAlDespertador = true
        arrancarMotor()
        if conexion == nil { conectarDespertador() }
    }

    func desactivarEscucha() {
        enviarAlDespertador = false
        conexion?.cancel()
        conexion = nil
        colaPrevio.sync { previo.removeAll() }
        if !capturando {
            motor.stop()
            motor.inputNode.removeTap(onBus: 0)
        }
    }

    func pedirPermisosYArrancar() {
        SFSpeechRecognizer.requestAuthorization { _ in }
        AVCaptureDevice.requestAccess(for: .audio) { [weak self] concedido in
            guard concedido, let self, self.enviarAlDespertador else { return }
            DispatchQueue.main.async {
                self.arrancarMotor()
                self.conectarDespertador()
            }
        }
    }

    // El micrófono queda abierto solo si la activación por voz está activa; si no,
    // se abre al pulsar el atajo y se cierra al terminar.
    private func arrancarMotor() {
        guard !motor.isRunning else { return }
        let entrada = motor.inputNode
        let formato = entrada.outputFormat(forBus: 0)
        convertidor = AVAudioConverter(from: formato, to: formato16k)
        entrada.removeTap(onBus: 0)
        entrada.installTap(onBus: 0, bufferSize: 2048, format: formato) { [weak self] buffer, _ in
            guard let self else { return }
            self.peticion?.append(buffer)
            if self.enviarAlDespertador && !self.capturando {
                self.guardarPrevio(buffer)
                self.enviar(buffer)
            }
        }
        motor.prepare()
        try? motor.start()
    }

    private func enviar(_ buffer: AVAudioPCMBuffer) {
        guard let convertidor, let conexion, conexion.state == .ready else { return }
        let capacidad = AVAudioFrameCount(Double(buffer.frameLength) * 16000 / buffer.format.sampleRate) + 32
        guard let salida = AVAudioPCMBuffer(pcmFormat: formato16k, frameCapacity: capacidad) else { return }
        var entregado = false
        convertidor.convert(to: salida, error: nil) { _, estado in
            if entregado { estado.pointee = .noDataNow; return nil }
            entregado = true
            estado.pointee = .haveData
            return buffer
        }
        guard let datos = salida.int16ChannelData, salida.frameLength > 0 else { return }
        guard hayVoz(datos[0], Int(salida.frameLength)) else { return }
        conexion.send(content: Data(bytes: datos[0], count: Int(salida.frameLength) * 2), completion: .idempotent)
    }

    // Puerta de silencio: solo se envía audio al detector cuando hay sonido por
    // encima del ruido de fondo (y 1,5 s más), así no gasta CPU con la sala en silencio.
    private var ruidoDeFondo: Float = -60
    private var colaRestante = 0

    private func hayVoz(_ muestras: UnsafePointer<Int16>, _ n: Int) -> Bool {
        var suma: Float = 0
        for i in 0..<n { let v = Float(muestras[i]) / 32768; suma += v * v }
        let db = 10 * log10(suma / Float(n) + 1e-10)
        // El fondo baja rápido y sube despacio: sigue al ruido, no a la voz.
        ruidoDeFondo = db < ruidoDeFondo ? db : ruidoDeFondo + 0.06
        if db > max(ruidoDeFondo + 11, -55) { colaRestante = Int(1.5 * 16000) }
        diagnostico(db)
        guard colaRestante > 0 else { return false }
        colaRestante -= n
        return true
    }

    private var ultimoDiag = Date.distantPast
    private func diagnostico(_ db: Float) {
        guard ProcessInfo.processInfo.environment["DJ_DIAG"] != nil || FileManager.default.fileExists(atPath: "/tmp/dj_diag"),
              Date().timeIntervalSince(ultimoDiag) > 0.5 else { return }
        ultimoDiag = Date()
        let linea = String(format: "%.1f dB  fondo %.1f  abierta %d\n", db, ruidoDeFondo, colaRestante > 0 ? 1 : 0)
        if let h = FileHandle(forWritingAtPath: "/tmp/dj_diag") { h.seekToEndOfFile(); h.write(Data(linea.utf8)); try? h.close() }
    }

    private func conectarDespertador() {
        let c = NWConnection(host: "127.0.0.1", port: 8766, using: .tcp)
        c.stateUpdateHandler = { [weak self] estado in
            switch estado {
            case .failed, .cancelled:
                // El cerebro pudo reiniciarse: se reintenta en unos segundos,
                // salvo que la escucha se haya apagado a propósito.
                DispatchQueue.main.asyncAfter(deadline: .now() + 3) {
                    guard let self, self.enviarAlDespertador, self.conexion === c else { return }
                    self.conexion = nil
                    self.conectarDespertador()
                }
            default: break
            }
        }
        c.start(queue: .main)
        conexion = c
        recibir(c)
    }

    private func recibir(_ c: NWConnection) {
        c.receive(minimumIncompleteLength: 1, maximumLength: 64) { [weak self] datos, _, terminado, error in
            if let datos, datos.contains(UInt8(ascii: "W")) {
                DispatchQueue.main.async { if !(self?.capturando ?? true) { self?.alActivarse?() } }
            }
            if terminado || error != nil { c.cancel(); return }
            self?.recibir(c)
        }
    }

    func capturar(silencioInicial: TimeInterval, usarPrevio: Bool = false, _ alTerminar: @escaping (String) -> Void) {
        guard let reconocedor else { alTerminar(""); return }
        arrancarMotor()
        self.alTerminar = alTerminar
        texto = ""
        capturando = true
        let peticion = SFSpeechAudioBufferRecognitionRequest()
        peticion.shouldReportPartialResults = true
        peticion.requiresOnDeviceRecognition = reconocedor.supportsOnDeviceRecognition
        peticion.contextualStrings = ["DJ", "Ghostemane", "Måneskin", "$uicideboy$", "Rammstein", "El Tri",
                                       "Kim Dracula", "Love Ghost", "YUNGBLUD", "Sleep Token", "Spotify", "lo-fi"]
        tarea = reconocedor.recognitionTask(with: peticion) { [weak self] resultado, error in
            guard let self else { return }
            if let resultado {
                self.texto = resultado.bestTranscription.formattedString
                self.reiniciarSilencio(self.silencio)
                if resultado.isFinal { self.terminarCaptura() }
            } else if error != nil {
                self.terminarCaptura()
            }
        }
        if usarPrevio {
            colaPrevio.sync { previo.forEach { peticion.append($0) }; previo.removeAll() }
        }
        self.peticion = peticion
        reiniciarSilencio(silencioInicial)
        DispatchQueue.main.asyncAfter(deadline: .now() + maximo) { [weak self] in self?.terminarCaptura() }
    }

    private func reiniciarSilencio(_ segundos: TimeInterval) {
        DispatchQueue.main.async {
            self.temporizador?.invalidate()
            self.temporizador = Timer.scheduledTimer(withTimeInterval: segundos, repeats: false) { [weak self] _ in
                self?.terminarCaptura()
            }
        }
    }

    func terminarCaptura() {
        DispatchQueue.main.async {
            guard self.capturando else { return }
            self.capturando = false
            self.temporizador?.invalidate()
            self.peticion?.endAudio()
            self.peticion = nil
            self.tarea?.cancel()
            if !self.enviarAlDespertador {
                self.motor.stop()
                self.motor.inputNode.removeTap(onBus: 0)
            }
            self.alTerminar?(Self.sinFraseDeActivacion(self.texto))
            self.alTerminar = nil
        }
    }

    /// Si la petición empieza con la frase de activación ("hey DJ, pon…"), se quita.
    static func sinFraseDeActivacion(_ texto: String) -> String {
        var t = texto.trimmingCharacters(in: .whitespacesAndNewlines)
        for prefijo in ["hey dj", "hey, dj", "hey deejay", "hey jarvis", "hey, jarvis", "jarvis", "oye dj", "ey dj", "hey"] {
            if t.lowercased().hasPrefix(prefijo) {
                t = String(t.dropFirst(prefijo.count)).trimmingCharacters(in: CharacterSet(charactersIn: " ,.¡!"))
                break
            }
        }
        return t
    }
}

// MARK: - Vigilante: salta lo bloqueado que se cuele (DJ, radios, playlists ajenas)

/// Spotify publica un aviso del sistema cada vez que cambia de canción; se usa
/// eso en lugar de preguntarle cada pocos segundos, así no gasta CPU en reposo.
final class Vigilante: NSObject {
    private var ultima: String?
    private var lista: (artistas: Set<String>, palabras: [String]) = ([], [])
    private var fechaLista: Date?
    private let archivo = FileManager.default.homeDirectoryForCurrentUser
        .appending(path: "spotify-voice-dj/conector/bloqueados.json")
    private let registro = FileManager.default.homeDirectoryForCurrentUser.appending(path: "spotify-voice-dj/cerebro.log")

    override init() {
        super.init()
        DistributedNotificationCenter.default().addObserver(
            self, selector: #selector(cambio(_:)),
            name: Notification.Name("com.spotify.client.PlaybackStateChanged"), object: nil)
    }

    static func clave(_ t: String) -> String {
        t.replacingOccurrences(of: "$", with: "s")
            .folding(options: [.caseInsensitive, .diacriticInsensitive], locale: nil)
            .filter { $0.isLetter || $0.isNumber }
    }

    private func recargarSiCambio() {
        let fecha = (try? archivo.resourceValues(forKeys: [.contentModificationDateKey]))?.contentModificationDate
        guard fecha != fechaLista, let datos = try? Data(contentsOf: archivo),
              let json = try? JSONSerialization.jsonObject(with: datos) as? [String: Any] else { return }
        fechaLista = fecha
        let artistas = (json["artistas"] as? [String] ?? []).map(Self.clave)
        let palabras = (json["palabras"] as? [String] ?? [])
            .map { $0.folding(options: [.caseInsensitive, .diacriticInsensitive], locale: nil) }
        lista = (Set(artistas), palabras)
    }

    @objc private func cambio(_ aviso: Notification) {
        guard let info = aviso.userInfo, info["Player State"] as? String == "Playing" else { return }
        let id = info["Track ID"] as? String
        guard id != ultima else { return }
        ultima = id
        recargarSiCambio()
        let artista = info["Artist"] as? String ?? ""
        let nombre = info["Name"] as? String ?? ""
        let artistas = artista.replacingOccurrences(of: " & ", with: ",").split(separator: ",").map { Self.clave(String($0)) }
        let nombrePlano = nombre.folding(options: [.caseInsensitive, .diacriticInsensitive], locale: nil)
        let bloqueado = artistas.contains { lista.artistas.contains($0) } || lista.palabras.contains { nombrePlano.contains($0) }
        guard bloqueado else { return }
        Spotify.siguiente()
        let linea = "\(Date().formatted(date: .numeric, time: .standard)) vigilante: saltada \(nombre) — \(artista)\n"
        if let h = try? FileHandle(forWritingTo: registro) {
            h.seekToEndOfFile(); h.write(Data(linea.utf8)); try? h.close()
        }
    }
}

// MARK: - Cerebro

enum Cerebro {
    static func pedir(_ texto: String) async -> String {
        var req = URLRequest(url: URL(string: "http://127.0.0.1:8765/pedir")!)
        req.httpMethod = "POST"
        req.timeoutInterval = 90
        req.httpBody = try? JSONSerialization.data(withJSONObject: ["texto": texto])
        do {
            let (datos, _) = try await URLSession.shared.data(for: req)
            let json = try JSONSerialization.jsonObject(with: datos) as? [String: Any]
            return json?["respuesta"] as? String ?? "No entendí la respuesta."
        } catch {
            return "El cerebro del DJ no responde."
        }
    }
}

// MARK: - Spotify (bajar el volumen mientras escucha)

enum Spotify {
    private static func ejecutar(_ codigo: String) -> String? {
        var error: NSDictionary?
        return NSAppleScript(source: codigo)?.executeAndReturnError(&error).stringValue
    }

    /// Baja la música para oírte mejor. Devuelve el volumen anterior, o nil si
    /// Spotify no estaba sonando.
    static func bajarVolumen() -> Int? {
        guard let actual = ejecutar("""
            if application "Spotify" is running then
              tell application "Spotify"
                if player state is playing then return sound volume as string
              end tell
            end if
            return ""
            """), let volumen = Int(actual) else { return nil }
        _ = ejecutar("tell application \"Spotify\" to set sound volume to \(min(volumen, 12))")
        return volumen
    }

    static func siguiente() {
        _ = ejecutar("tell application \"Spotify\" to next track")
    }

    static func restaurarVolumen(_ volumen: Int?) {
        guard let volumen else { return }
        _ = ejecutar("tell application \"Spotify\" to set sound volume to \(volumen)")
    }
}

// MARK: - Atajo global ⌥Espacio (Carbon: no necesita permiso de accesibilidad)

enum Atajo {
    private static var acciones: [UInt32: () -> Void] = [:]
    private static var referencias: [EventHotKeyRef?] = []
    private static var instalado = false

    /// Espacio + modificadores (Carbon: no necesita permiso de accesibilidad).
    static func registrar(id: UInt32, modificadores: Int, _ accion: @escaping () -> Void) {
        acciones[id] = accion
        if !instalado {
            instalado = true
            var tipo = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))
            InstallEventHandler(GetApplicationEventTarget(), { _, evento, _ in
                var pulsado = EventHotKeyID()
                GetEventParameter(evento, EventParamName(kEventParamDirectObject), EventParamType(typeEventHotKeyID),
                                  nil, MemoryLayout<EventHotKeyID>.size, nil, &pulsado)
                let id = pulsado.id
                DispatchQueue.main.async { Atajo.acciones[id]?() }
                return noErr
            }, 1, &tipo, nil, nil)
        }
        var referencia: EventHotKeyRef?
        let hotKeyID = EventHotKeyID(signature: OSType(0x444A_5631), id: id) // "DJV1"
        RegisterEventHotKey(UInt32(kVK_Space), UInt32(modificadores), hotKeyID, GetApplicationEventTarget(), 0, &referencia)
        referencias.append(referencia)
    }
}
