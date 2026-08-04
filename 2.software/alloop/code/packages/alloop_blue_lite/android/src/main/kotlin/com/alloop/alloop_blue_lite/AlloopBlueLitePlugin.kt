package com.alloop.alloop_blue_lite

import android.content.Context
import android.os.Handler
import android.os.Looper
import com.alloop.core.api.AlloopCore
import com.alloop.core.api.ConnectionCallback
import com.alloop.core.api.DeviceStatusCallback
import com.alloop.core.api.HistoryCallback
import com.alloop.core.api.RealtimeCallback
import com.alloop.core.api.ScanCallback
import io.flutter.embedding.engine.plugins.FlutterPlugin
import io.flutter.plugin.common.EventChannel
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import io.flutter.plugin.common.MethodChannel.MethodCallHandler
import io.flutter.plugin.common.MethodChannel.Result

/**
 * [AlloopBlueLitePlugin] is a zero-logic bridge between the Dart-facing platform channels and
 * the [AlloopCore] facade: it translates method calls into facade calls and facade callbacks
 * into event-channel payloads. It holds no protocol knowledge, no state machine and does no
 * byte handling — all of that lives in `alloop-core`.
 */
class AlloopBlueLitePlugin :
    FlutterPlugin,
    MethodCallHandler {
    private val mainHandler = Handler(Looper.getMainLooper())
    private var applicationContext: Context? = null

    private lateinit var methodChannel: MethodChannel

    private lateinit var scanChannel: EventChannel
    private lateinit var connectionChannel: EventChannel
    private lateinit var deviceStatusChannel: EventChannel
    private lateinit var spo2Channel: EventChannel
    private lateinit var ppgChannel: EventChannel
    private lateinit var historyChannel: EventChannel

    private var scanSink: EventChannel.EventSink? = null
    private var connectionSink: EventChannel.EventSink? = null
    private var deviceStatusSink: EventChannel.EventSink? = null
    private var spo2Sink: EventChannel.EventSink? = null
    private var ppgSink: EventChannel.EventSink? = null
    private var historySink: EventChannel.EventSink? = null

    override fun onAttachedToEngine(binding: FlutterPlugin.FlutterPluginBinding) {
        val messenger = binding.binaryMessenger
        applicationContext = binding.applicationContext

        methodChannel = MethodChannel(messenger, "alloop_blue_lite/methods")
        methodChannel.setMethodCallHandler(this)

        scanChannel = EventChannel(messenger, "alloop_blue_lite/events/scan")
        scanChannel.setStreamHandler(
            object : EventChannel.StreamHandler {
                override fun onListen(arguments: Any?, events: EventChannel.EventSink) {
                    scanSink = events
                    AlloopCore.setScanCallback(
                        object : ScanCallback {
                            override fun onDevice(map: Map<String, Any>) {
                                postToSink(scanSink, map)
                            }
                        },
                    )
                }

                override fun onCancel(arguments: Any?) {
                    scanSink = null
                }
            },
        )

        connectionChannel = EventChannel(messenger, "alloop_blue_lite/events/connection")
        connectionChannel.setStreamHandler(
            object : EventChannel.StreamHandler {
                override fun onListen(arguments: Any?, events: EventChannel.EventSink) {
                    connectionSink = events
                    AlloopCore.setConnectionCallback(
                        object : ConnectionCallback {
                            override fun onStateChanged(deviceId: String, state: String, errorCode: String?) {
                                postToSink(
                                    connectionSink,
                                    mapOf("deviceId" to deviceId, "state" to state, "errorCode" to errorCode),
                                )
                            }
                        },
                    )
                }

                override fun onCancel(arguments: Any?) {
                    connectionSink = null
                }
            },
        )

        deviceStatusChannel = EventChannel(messenger, "alloop_blue_lite/events/device_status")
        deviceStatusChannel.setStreamHandler(
            object : EventChannel.StreamHandler {
                override fun onListen(arguments: Any?, events: EventChannel.EventSink) {
                    deviceStatusSink = events
                    AlloopCore.setDeviceStatusCallback(
                        object : DeviceStatusCallback {
                            override fun onStatus(deviceId: String, map: Map<String, Any>) {
                                postToSink(deviceStatusSink, mapOf("deviceId" to deviceId) + map)
                            }
                        },
                    )
                }

                override fun onCancel(arguments: Any?) {
                    deviceStatusSink = null
                }
            },
        )

        // spo2 and ppg are both fed by the single AlloopCore.RealtimeCallback; whichever of the
        // two channels starts listening first installs it, and it routes each payload kind to
        // the sink that owns it (nulled out until that channel's own onListen runs).
        val realtimeCallback =
            object : RealtimeCallback {
                override fun onSpo2Result(map: Map<String, Any?>) {
                    postToSink(spo2Sink, map + mapOf("kind" to "result"))
                }

                override fun onVerifySpo2(map: Map<String, Any>) {
                    postToSink(spo2Sink, map + mapOf("kind" to "verify"))
                }

                override fun onPpg(map: Map<String, Any>) {
                    postToSink(ppgSink, map + mapOf("kind" to "ppg"))
                }

                override fun onAcc(map: Map<String, Any>) {
                    postToSink(ppgSink, map + mapOf("kind" to "acc"))
                }
            }

        spo2Channel = EventChannel(messenger, "alloop_blue_lite/events/spo2")
        spo2Channel.setStreamHandler(
            object : EventChannel.StreamHandler {
                override fun onListen(arguments: Any?, events: EventChannel.EventSink) {
                    spo2Sink = events
                    AlloopCore.setRealtimeCallback(realtimeCallback)
                }

                override fun onCancel(arguments: Any?) {
                    spo2Sink = null
                }
            },
        )

        ppgChannel = EventChannel(messenger, "alloop_blue_lite/events/ppg")
        ppgChannel.setStreamHandler(
            object : EventChannel.StreamHandler {
                override fun onListen(arguments: Any?, events: EventChannel.EventSink) {
                    ppgSink = events
                    AlloopCore.setRealtimeCallback(realtimeCallback)
                }

                override fun onCancel(arguments: Any?) {
                    ppgSink = null
                }
            },
        )

        historyChannel = EventChannel(messenger, "alloop_blue_lite/events/history")
        historyChannel.setStreamHandler(
            object : EventChannel.StreamHandler {
                override fun onListen(arguments: Any?, events: EventChannel.EventSink) {
                    historySink = events
                    AlloopCore.setHistoryCallback(
                        object : HistoryCallback {
                            override fun onTypeStarted(type: String, total: Int?) {
                                postToSink(
                                    historySink,
                                    mapOf("event" to "typeStarted", "type" to type, "total" to total),
                                )
                            }

                            override fun onRecord(type: String, map: Map<String, Any>, index: Int, total: Int?) {
                                postToSink(
                                    historySink,
                                    mapOf(
                                        "event" to "record",
                                        "type" to type,
                                        "record" to map,
                                        "index" to index,
                                        "total" to total,
                                    ),
                                )
                            }

                            override fun onTypeCompleted(type: String, count: Int) {
                                postToSink(
                                    historySink,
                                    mapOf("event" to "typeCompleted", "type" to type, "count" to count),
                                )
                            }

                            override fun onAllCompleted(counts: Map<String, Int>) {
                                postToSink(historySink, mapOf("event" to "allCompleted", "counts" to counts))
                            }

                            override fun onError(code: String, message: String) {
                                postToSink(
                                    historySink,
                                    mapOf("event" to "error", "code" to code, "message" to message),
                                )
                            }
                        },
                    )
                }

                override fun onCancel(arguments: Any?) {
                    historySink = null
                }
            },
        )
    }

    override fun onMethodCall(call: MethodCall, result: Result) {
        when (call.method) {
            "initialize" -> {
                val context: Context = applicationContext ?: run {
                    result.error("NOT_INITIALIZED", "plugin not attached to engine", null)
                    return
                }
                AlloopCore.init(context)
                result.success(null)
            }

            "startScan" -> {
                val nameFilter = call.argument<String>("nameFilter")
                val timeoutMs = call.argument<Number>("timeoutMs")?.toLong()
                AlloopCore.startScan(nameFilter, timeoutMs)
                result.success(null)
            }

            "stopScan" -> {
                AlloopCore.stopScan()
                result.success(null)
            }

            "connect" -> {
                val deviceId = call.requireDeviceId(result) ?: return
                AlloopCore.connect(deviceId)
                result.success(null)
            }

            "disconnect" -> {
                val deviceId = call.requireDeviceId(result) ?: return
                AlloopCore.disconnect(deviceId)
                result.success(null)
            }

            "getDeviceInfo" -> {
                val deviceId = call.requireDeviceId(result) ?: return
                AlloopCore.getDeviceInfo(deviceId) { r ->
                    mainHandler.post {
                        r.fold({ result.success(it) }, { result.error(codeOf(it), it.message, null) })
                    }
                }
            }

            "queryDeviceStatus" -> {
                val deviceId = call.requireDeviceId(result) ?: return
                AlloopCore.queryDeviceStatus(deviceId) { r ->
                    mainHandler.post {
                        r.fold({ result.success(it) }, { result.error(codeOf(it), it.message, null) })
                    }
                }
            }

            "startSpo2Verification" -> {
                val deviceId = call.requireDeviceId(result) ?: return
                AlloopCore.startSpo2Verification(deviceId) { r ->
                    mainHandler.post {
                        r.fold({ result.success(null) }, { result.error(codeOf(it), it.message, null) })
                    }
                }
            }

            "stopMeasurement" -> {
                val deviceId = call.requireDeviceId(result) ?: return
                AlloopCore.stopMeasurement(deviceId) { r ->
                    mainHandler.post {
                        r.fold({ result.success(null) }, { result.error(codeOf(it), it.message, null) })
                    }
                }
            }

            "syncHistory" -> {
                val deviceId = call.requireDeviceId(result) ?: return
                AlloopCore.syncHistory(deviceId)
                result.success(null)
            }

            else -> result.notImplemented()
        }
    }

    override fun onDetachedFromEngine(binding: FlutterPlugin.FlutterPluginBinding) {
        methodChannel.setMethodCallHandler(null)
        scanChannel.setStreamHandler(null)
        connectionChannel.setStreamHandler(null)
        deviceStatusChannel.setStreamHandler(null)
        spo2Channel.setStreamHandler(null)
        ppgChannel.setStreamHandler(null)
        historyChannel.setStreamHandler(null)

        scanSink = null
        connectionSink = null
        deviceStatusSink = null
        spo2Sink = null
        ppgSink = null
        historySink = null

        AlloopCore.setScanCallback(null)
        AlloopCore.setConnectionCallback(null)
        AlloopCore.setDeviceStatusCallback(null)
        AlloopCore.setRealtimeCallback(null)
        AlloopCore.setHistoryCallback(null)

        applicationContext = null
    }

    /** Extracts `deviceId` from [MethodCall] arguments, failing [result] with a clear error if absent. */
    private fun MethodCall.requireDeviceId(result: Result): String? {
        val deviceId = argument<String>("deviceId")
        if (deviceId == null) {
            result.error("INVALID_ARGUMENT", "missing required argument 'deviceId'", null)
            return null
        }
        return deviceId
    }

    /** Posts [map] to [sink] on the main thread; silently dropped if no listener is attached yet. */
    private fun postToSink(sink: EventChannel.EventSink?, map: Map<String, Any?>) {
        if (sink == null) return
        mainHandler.post { sink.success(map) }
    }

    /**
     * Extracts a stable machine-readable error code from an [AlloopCore] callback failure.
     *
     * `AlloopCoreException` lives in the public `com.alloop.core.api` package (kept by
     * alloop-core's proguard rules), so it is visible across the AAR boundary and can be
     * cast to directly here.
     */
    private fun codeOf(t: Throwable): String =
        (t as? com.alloop.core.api.AlloopCoreException)?.code ?: "CORE_ERROR"
}
