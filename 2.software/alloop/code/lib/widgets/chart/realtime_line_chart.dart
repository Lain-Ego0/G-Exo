import 'dart:math' as math;
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:flutter_screenutil/flutter_screenutil.dart';

/// A data point.
///
/// Represents a point in a 2D coordinate system, where x is usually a timestamp
/// and y is a value.
class DataPoint {
  final double x;
  final double y;

  const DataPoint(this.x, this.y);

  @override
  bool operator ==(Object other) {
    if (identical(this, other)) return true;
    return other is DataPoint && other.x == x && other.y == y;
  }

  @override
  int get hashCode => Object.hash(x, y);

  @override
  String toString() => 'DataPoint($x, $y)';
}

/// Real-time scrolling line chart.
///
/// Key features:
/// - Fixed X-axis tick positions (time labels update dynamically)
/// - Data flows from right to left (real-time scrolling)
/// - Adaptive Y-axis range (optional)
/// - Two-finger Y-axis zoom
/// - High-performance Canvas drawing
/// - Multi-channel data support
///
/// Use cases:
/// - PPG real-time chart (100Hz, 3 channels)
/// - ACC real-time chart (25Hz, 3 axes)
/// - Other high-frequency sensor data streams
class RealTimeLineChart extends StatefulWidget {
  /// List of data series (supports multiple lines)
  final List<ChartDataSeries> series;

  /// Chart title
  final String title;

  /// Time window (seconds), controls how much data is displayed
  final double windowSeconds;

  /// Fixed Y-axis range (used when autoScaleY = false)
  final double fixedMinY;
  final double fixedMaxY;

  /// Y-axis adaptive range toggle
  final bool autoScaleY;

  /// Y-axis padding ratio (adds 10% padding in adaptive mode)
  final double yPaddingRatio;

  /// Time reference point (used to compute X-axis time labels)
  final DateTime? referenceTime;

  /// Chart height
  final double height;

  /// Vertical padding of the chart container (defaults to 8.h)
  final double? verticalPadding;

  /// Spacing between the title and the chart (defaults to 6.h)
  final double? titleSpacing;

  /// Whether zooming is allowed
  final bool allowZoom;

  /// Reset-view signal (each increment resets zoom and pan)
  final int resetSignal;

  /// Touched data point callback (returns the data point, series index, and screen position)
  final void Function(
    DataPoint dataPoint,
    int seriesIndex,
    Offset screenPosition,
  )?
  onDataPointTouched;

  /// Touch-end callback
  final VoidCallback? onTouchEnd;

  const RealTimeLineChart({
    super.key,
    required this.series,
    required this.title,
    this.windowSeconds = 5.0,
    this.fixedMinY = 0.0,
    this.fixedMaxY = 1.0,
    this.autoScaleY = true,
    this.yPaddingRatio = 0.1,
    this.referenceTime,
    this.height = 140,
    this.verticalPadding,
    this.titleSpacing,
    this.allowZoom = true,
    this.resetSignal = 0,
    this.onDataPointTouched,
    this.onTouchEnd,
  });

  @override
  State<RealTimeLineChart> createState() => _RealTimeLineChartState();
}

class _RealTimeLineChartState extends State<RealTimeLineChart> {
  /// Y-axis zoom scale (1.0 = default, >1.0 = zoomed in)
  double _yZoomScale = 1.0;

  /// Position of the Y-axis viewport center within the data range (0.0 = bottom, 1.0 = top)
  double _viewportCenter = 0.5;

  /// Timestamp of the latest data (used to compute scrolling)
  double _currentTime = 0.0;

  /// Starting value of the gesture zoom
  double _startZoomScale = 1.0;

  /// Viewport center at the start of the gesture zoom
  double _startViewportCenter = 0.5;

  /// The touched data point (used to display the tooltip)
  _TouchedDataPoint? _touchedDataPoint;

  @override
  void initState() {
    super.initState();
    _updateCurrentTime();
  }

  @override
  void didUpdateWidget(covariant RealTimeLineChart oldWidget) {
    super.didUpdateWidget(oldWidget);

    final oldMaxTime = _currentTime;

    // Update the current timestamp
    _updateCurrentTime();

    // Trigger a repaint if the data has updated
    if (_currentTime != oldMaxTime) {
      setState(() {});
    }

    // Reset the view when the reset signal changes
    if (oldWidget.resetSignal != widget.resetSignal) {
      setState(() {
        _yZoomScale = 1.0;
        _viewportCenter = 0.5;
      });
    }
  }

  /// Updates the current timestamp (finds the latest data point across all series).
  void _updateCurrentTime() {
    double maxTime = 0.0;
    for (final series in widget.series) {
      if (series.data.isNotEmpty) {
        final lastTime = series.data.last.x.toDouble();
        if (lastTime > maxTime) {
          maxTime = lastTime;
        }
      }
    }
    if (maxTime > 0) {
      _currentTime = maxTime;
    }
  }

  /// Returns the timestamp of the earliest data point.
  double _getMinDataTime() {
    double minTime = double.infinity;
    for (final series in widget.series) {
      if (series.data.isNotEmpty) {
        final firstTime = series.data.first.x.toDouble();
        if (firstTime < minTime) {
          minTime = firstTime;
        }
      }
    }
    return minTime == double.infinity ? 0.0 : minTime;
  }

  /// Checks whether any series has data-point markers enabled.
  bool _hasDotsEnabled() {
    return widget.series.any((series) => series.showDots);
  }

  /// Handles a touch event (finds the nearest data point).
  void _handleTouch(Offset localPosition) {
    // Get the actual render size (matching the size used in the Painter)
    final renderBox = context.findRenderObject() as RenderBox?;
    if (renderBox == null) return;

    final actualSize = renderBox.size;

    // Check whether the touch is within the chart area
    if (localPosition.dx < _RealTimeChartPainter.leftMargin ||
        localPosition.dy < _RealTimeChartPainter.topMargin ||
        localPosition.dy >
            actualSize.height - _RealTimeChartPainter.bottomMargin) {
      setState(() {
        _touchedDataPoint = null;
      });
      return;
    }

    // Compute the Y-axis range
    final baseYRange = _calculateYRange();

    // Create the coordinate transformer (using the same size as the Painter)
    final chartRect = Rect.fromLTWH(
      _RealTimeChartPainter.leftMargin,
      _RealTimeChartPainter.topMargin,
      actualSize.width -
          _RealTimeChartPainter.leftMargin -
          _RealTimeChartPainter.rightMargin,
      actualSize.height -
          _RealTimeChartPainter.topMargin -
          _RealTimeChartPainter.bottomMargin,
    );

    final transform = _ChartTransform(
      chartRect: chartRect,
      windowSeconds: widget.windowSeconds,
      currentTime: _currentTime,
      minY: baseYRange.min,
      maxY: baseYRange.max,
      yZoomScale: _yZoomScale,
      viewportCenter: _viewportCenter,
      minDataTime: _getMinDataTime(),
    );

    // Find the nearest data point
    _TouchedDataPoint? nearestPoint;
    double minDistance = double.infinity;

    for (
      int seriesIndex = 0;
      seriesIndex < widget.series.length;
      seriesIndex++
    ) {
      final series = widget.series[seriesIndex];

      // Filter visible data points (add a tolerance to avoid boundary-point flicker)
      final visibleData = series.data.where((spot) {
        return _currentTime - spot.x < widget.windowSeconds + 0.1;
      }).toList();

      for (final dataPoint in visibleData) {
        final screenPoint = transform.dataToScreen(dataPoint);

        // Compute the horizontal distance (mainly around the X axis)
        final horizontalDistance = (screenPoint.dx - localPosition.dx).abs();

        // Only consider points within 30 pixels on the X axis
        if (horizontalDistance < 30 && horizontalDistance < minDistance) {
          minDistance = horizontalDistance;
          nearestPoint = _TouchedDataPoint(
            dataPoint: dataPoint,
            screenPosition: screenPoint,
            seriesIndex: seriesIndex,
            color: series.color,
            seriesName: series.name,
          );
        }
      }
    }

    setState(() {
      _touchedDataPoint = nearestPoint;
    });

    // Trigger the callback
    if (nearestPoint != null) {
      widget.onDataPointTouched?.call(
        nearestPoint.dataPoint,
        nearestPoint.seriesIndex,
        nearestPoint.screenPosition,
      );
    }
  }

  /// Computes the Y-axis range (used for touch handling).
  _YAxisRange _calculateYRange() {
    if (!widget.autoScaleY) {
      final span = widget.fixedMaxY - widget.fixedMinY;
      final interval = _calculateOptimalInterval(span);
      return _YAxisRange(
        min: widget.fixedMinY,
        max: widget.fixedMaxY,
        interval: interval,
      );
    }

    double minY = double.infinity;
    double maxY = double.negativeInfinity;

    for (final seriesItem in widget.series) {
      for (final spot in seriesItem.data) {
        // Add a tolerance to avoid boundary-point flicker
        if (_currentTime - spot.x < widget.windowSeconds + 0.1) {
          if (spot.y < minY) minY = spot.y;
          if (spot.y > maxY) maxY = spot.y;
        }
      }
    }

    if (minY == double.infinity) {
      final span = widget.fixedMaxY - widget.fixedMinY;
      final interval = _calculateOptimalInterval(span);
      return _YAxisRange(
        min: widget.fixedMinY,
        max: widget.fixedMaxY,
        interval: interval,
      );
    }

    final padding = (maxY - minY) * widget.yPaddingRatio;
    minY -= padding;
    maxY += padding;

    const minSpan = 1.0;
    if (maxY - minY < minSpan) {
      final center = (minY + maxY) / 2;
      minY = center - minSpan / 2;
      maxY = center + minSpan / 2;
    }

    final span = maxY - minY;
    final interval = _calculateOptimalInterval(span);
    final niceMin = (minY / interval).floorToDouble() * interval;
    final niceMax = (maxY / interval).ceilToDouble() * interval;

    return _YAxisRange(min: niceMin, max: niceMax, interval: interval);
  }

  /// Computes the optimal tick interval.
  double _calculateOptimalInterval(double span) {
    if (span <= 0) return 1.0;

    const targetTickCount = 5;
    final roughInterval = span / targetTickCount;
    final exponent = (math.log(roughInterval) / math.ln10).floor();
    final powerOf10 = math.pow(10, exponent);
    final normalized = roughInterval / powerOf10;

    double standardInterval;
    if (normalized < 1.5) {
      standardInterval = 1;
    } else if (normalized < 3.5) {
      standardInterval = 2;
    } else if (normalized < 7.5) {
      standardInterval = 5;
    } else {
      standardInterval = 10;
    }

    return standardInterval * powerOf10;
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Container(
      color: theme.cardColor,
      padding: EdgeInsets.symmetric(vertical: widget.verticalPadding ?? 8.h),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Title row (with reset button)
          Padding(
            padding: EdgeInsets.symmetric(horizontal: 12.w),
            child: Row(
              children: [
                Expanded(
                  child: Text(
                    widget.title,
                    style: TextStyle(
                      fontSize: 13.sp,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
                // Show the reset button while zoomed
                if (widget.allowZoom && _yZoomScale > 1.01)
                  TextButton.icon(
                    onPressed: () {
                      setState(() {
                        _yZoomScale = 1.0;
                        _viewportCenter = 0.5;
                      });
                    },
                    icon: Icon(Icons.zoom_out_map, size: 14.r),
                    label: Text('Reset', style: TextStyle(fontSize: 11.sp)),
                    style: TextButton.styleFrom(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 8,
                        vertical: 4,
                      ),
                      minimumSize: Size.zero,
                      tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                    ),
                  ),
              ],
            ),
          ),
          SizedBox(height: widget.titleSpacing ?? 6.h),
          // Chart body
          SizedBox(height: widget.height, child: _buildChart()),
        ],
      ),
    );
  }

  /// Builds the chart body.
  Widget _buildChart() {
    if (widget.series.isEmpty || widget.series.every((s) => s.data.isEmpty)) {
      return const _EmptyChart();
    }

    return GestureDetector(
      behavior: HitTestBehavior.translucent,
      // Single-finger touch (used for data-point detection)
      // Enable touch detection when zoom is disabled and dot markers are shown
      onTapDown: !widget.allowZoom && _hasDotsEnabled()
          ? (details) {
              _handleTouch(details.localPosition);
            }
          : null,
      onPanUpdate: !widget.allowZoom && _hasDotsEnabled()
          ? (details) {
              _handleTouch(details.localPosition);
            }
          : null,
      onPanEnd: !widget.allowZoom && _hasDotsEnabled()
          ? (_) {
              setState(() {
                _touchedDataPoint = null;
              });
              widget.onTouchEnd?.call();
            }
          : null,
      // Two-finger Y-axis zoom
      onScaleStart: widget.allowZoom
          ? (details) {
              _startZoomScale = _yZoomScale;
              _startViewportCenter = _viewportCenter;
            }
          : null,
      onScaleUpdate: widget.allowZoom
          ? (details) {
              if (details.pointerCount == 2) {
                // Two-finger zoom
                setState(() {
                  final newZoomScale = (_startZoomScale * details.scale).clamp(
                    1.0,
                    10.0,
                  );

                  // Keep the viewport center fixed while zooming
                  _viewportCenter = _startViewportCenter;
                  _yZoomScale = newZoomScale;
                });
              } else if (details.pointerCount == 1 && _yZoomScale > 1.01) {
                // Single-finger drag (only allowed after zooming)
                setState(() {
                  // Compute the drag offset (vertical direction)
                  // focalPointDelta.dy > 0 means dragging down, which should move the chart up (increase viewportCenter)
                  final dragDelta = details.focalPointDelta.dy / 200.0;

                  // Compute the draggable range
                  // At zoom = 2x, the visible range is 50%, so it can drag from 25% to 75%
                  // At zoom = 10x, the visible range is 10%, so it can drag from 5% to 95%
                  final visibleRatio = 1.0 / _yZoomScale;
                  final minCenter = visibleRatio / 2;
                  final maxCenter = 1.0 - visibleRatio / 2;

                  _viewportCenter = (_viewportCenter + dragDelta).clamp(
                    minCenter,
                    maxCenter,
                  );
                });
              }
            }
          : null,
      child: RepaintBoundary(
        child: CustomPaint(
          painter: _RealTimeChartPainter(
            series: widget.series,
            windowSeconds: widget.windowSeconds,
            currentTime: _currentTime,
            fixedMinY: widget.fixedMinY,
            fixedMaxY: widget.fixedMaxY,
            autoScaleY: widget.autoScaleY,
            yPaddingRatio: widget.yPaddingRatio,
            yZoomScale: _yZoomScale,
            viewportCenter: _viewportCenter,
            referenceTime: widget.referenceTime,
            touchedDataPoint: _touchedDataPoint,
          ),
          size: Size.infinite,
        ),
      ),
    );
  }
}

/// Data series definition.
///
/// Represents a single line in the chart along with its related properties.
class ChartDataSeries {
  /// List of data points (sorted by time)
  final List<DataPoint> data;

  /// Line color
  final Color color;

  /// Series name (used for the legend)
  final String? name;

  /// Line width (pixels)
  final double strokeWidth;

  /// Whether to show point markers
  final bool showDots;

  const ChartDataSeries({
    required this.data,
    required this.color,
    this.name,
    this.strokeWidth = 1.2,
    this.showDots = false,
  });
}

/// Real-time chart painter.
///
/// Draws directly with the Canvas API for high performance.
class _RealTimeChartPainter extends CustomPainter {
  final List<ChartDataSeries> series;
  final double windowSeconds;
  final double currentTime;
  final double fixedMinY;
  final double fixedMaxY;
  final bool autoScaleY;
  final double yPaddingRatio;
  final double yZoomScale;
  final double viewportCenter;
  final DateTime? referenceTime;
  final _TouchedDataPoint? touchedDataPoint;

  _RealTimeChartPainter({
    required this.series,
    required this.windowSeconds,
    required this.currentTime,
    required this.fixedMinY,
    required this.fixedMaxY,
    required this.autoScaleY,
    required this.yPaddingRatio,
    required this.yZoomScale,
    required this.viewportCenter,
    this.referenceTime,
    this.touchedDataPoint,
  });

  // Chart margin constants
  static final double leftMargin = 40.w; // Space for Y-axis labels
  static final double rightMargin = 10.w;
  static final double topMargin = 10.h;
  static final double bottomMargin = 30.h; // Space for X-axis labels

  final _gridPaint = Paint()
    ..color = Colors.grey.shade200
    ..strokeWidth = 1.r;

  // Axes (left Y axis + bottom X axis) use a darker color
  final _axisPaint = Paint()
    ..color = Colors.grey.shade400
    ..strokeWidth = 1.5.r
    ..style = PaintingStyle.stroke;

  @override
  void paint(Canvas canvas, Size size) {
    // 1. Compute the drawing area (minus margins)
    final chartRect = Rect.fromLTWH(
      leftMargin,
      topMargin,
      size.width - leftMargin - rightMargin,
      size.height - topMargin - bottomMargin,
    );

    // 2. Compute the Y-axis range (base range, unzoomed)
    final baseYRange = _calculateYRange();

    // 3. Compute the visible Y-axis range after zoom
    final visibleYRange = _calculateVisibleYRange(baseYRange);

    // 4. Create the coordinate transformer
    final transform = _ChartTransform(
      chartRect: chartRect,
      windowSeconds: windowSeconds,
      currentTime: currentTime,
      minY: baseYRange.min,
      maxY: baseYRange.max,
      yZoomScale: yZoomScale,
      viewportCenter: viewportCenter,
      minDataTime: _getMinDataTimeFromSeries(series),
    );

    // 5. Clip the drawing area (to prevent drawing beyond the chart bounds)
    canvas.save();
    canvas.clipRect(chartRect);

    // 6. Draw the background grid (using the visible range)
    _drawGrid(canvas, chartRect, transform, visibleYRange);

    // 7. Draw the data lines
    for (final seriesItem in series) {
      _drawSeries(canvas, seriesItem, transform);
    }

    canvas.restore();

    // 8. Draw the X axis (fixed positions, dynamic labels)
    _drawXAxis(canvas, chartRect);

    // 9. Draw the Y axis (using the visible range)
    _drawYAxis(canvas, chartRect, visibleYRange);

    // 10. Draw the border
    _drawBorder(canvas, chartRect);

    // 11. Draw the touch highlight (enlarged dot)
    // Note: the screen coordinates must be recomputed because the data may have scrolled
    if (touchedDataPoint != null) {
      _drawTouchedPointHighlight(canvas, touchedDataPoint!, transform);
    }
  }

  /// Computes the Y-axis range.
  _YAxisRange _calculateYRange() {
    if (!autoScaleY) {
      // Fixed-range mode: still compute a suitable tick interval from the range
      final span = fixedMaxY - fixedMinY;
      final interval = _calculateOptimalInterval(span);
      return _YAxisRange(min: fixedMinY, max: fixedMaxY, interval: interval);
    }

    // Adaptive mode: compute the actual range of the visible data
    double minY = double.infinity;
    double maxY = double.negativeInfinity;

    for (final seriesItem in series) {
      for (final spot in seriesItem.data) {
        // Only consider data within the time window (add a tolerance to avoid boundary-point flicker)
        if (currentTime - spot.x < windowSeconds + 0.1) {
          if (spot.y < minY) minY = spot.y;
          if (spot.y > maxY) maxY = spot.y;
        }
      }
    }

    if (minY == double.infinity) {
      // No data, use the fixed range
      final span = fixedMaxY - fixedMinY;
      final interval = _calculateOptimalInterval(span);
      return _YAxisRange(min: fixedMinY, max: fixedMaxY, interval: interval);
    }

    // Add padding
    final padding = (maxY - minY) * yPaddingRatio;
    minY -= padding;
    maxY += padding;

    // Ensure a minimum range (to avoid floating-point precision issues)
    const minSpan = 1.0;
    if (maxY - minY < minSpan) {
      final center = (minY + maxY) / 2;
      minY = center - minSpan / 2;
      maxY = center + minSpan / 2;
    }

    // Compute a nice tick interval
    final span = maxY - minY;
    final interval = _calculateOptimalInterval(span);
    final niceMin = (minY / interval).floorToDouble() * interval;
    final niceMax = (maxY / interval).ceilToDouble() * interval;

    return _YAxisRange(min: niceMin, max: niceMax, interval: interval);
  }

  /// Returns the timestamp of the earliest data point (from the series data).
  double _getMinDataTimeFromSeries(List<ChartDataSeries> seriesList) {
    double minTime = double.infinity;
    for (final seriesItem in seriesList) {
      if (seriesItem.data.isNotEmpty) {
        final firstTime = seriesItem.data.first.x.toDouble();
        if (firstTime < minTime) {
          minTime = firstTime;
        }
      }
    }
    return minTime == double.infinity ? 0.0 : minTime;
  }

  /// Computes the optimal tick interval (ensuring 5-6 ticks).
  double _calculateOptimalInterval(double span) {
    if (span <= 0) return 1.0;

    // Target number of ticks
    const targetTickCount = 5;

    // Rough interval
    final roughInterval = span / targetTickCount;

    // Compute the order of magnitude
    final exponent = (math.log(roughInterval) / math.ln10).floor();
    final powerOf10 = math.pow(10, exponent);

    // Normalize to the [1, 10) range
    final normalized = roughInterval / powerOf10;

    // Choose a standard interval: 1, 2, 5, 10
    double standardInterval;
    if (normalized < 1.5) {
      standardInterval = 1;
    } else if (normalized < 3.5) {
      standardInterval = 2;
    } else if (normalized < 7.5) {
      standardInterval = 5;
    } else {
      standardInterval = 10;
    }

    return standardInterval * powerOf10;
  }

  /// Computes the visible Y-axis range after zoom.
  ///
  /// When the user zooms in, the Y-axis labels should show finer ticks.
  /// For example: base range [5, 10, 15, 20, 25, 30]
  ///      zoomed in, visible [15, 16, 17, 18, 19, 20]
  ///      after dragging, visible [18, 19, 20, 21, 22, 23]
  _YAxisRange _calculateVisibleYRange(_YAxisRange baseRange) {
    if (yZoomScale <= 1.01) {
      // Not zoomed, return the base range
      return baseRange;
    }

    // Compute the size of the visible range after zoom
    final baseSpan = baseRange.max - baseRange.min;
    final visibleSpan = baseSpan / yZoomScale;

    // Compute the visible range based on viewportCenter
    // viewportCenter = 0.5 means viewing the middle
    // viewportCenter = 0.0 means viewing the bottom
    // viewportCenter = 1.0 means viewing the top
    final centerValue = baseRange.min + viewportCenter * baseSpan;

    // Compute the min and max of the visible range
    var visibleMin = centerValue - visibleSpan / 2;
    var visibleMax = centerValue + visibleSpan / 2;

    // Ensure the visible range does not exceed the base range (it shouldn't in theory, since dragging is already clamped)
    visibleMin = visibleMin.clamp(baseRange.min, baseRange.max);
    visibleMax = visibleMax.clamp(baseRange.min, baseRange.max);

    // Compute the new (finer) tick interval
    final actualSpan = visibleMax - visibleMin;
    final newInterval = _calculateOptimalInterval(actualSpan);

    // Align to ticks
    final niceMin = (visibleMin / newInterval).floorToDouble() * newInterval;
    final niceMax = (visibleMax / newInterval).ceilToDouble() * newInterval;

    return _YAxisRange(min: niceMin, max: niceMax, interval: newInterval);
  }

  /// Draws the grid.
  void _drawGrid(
    Canvas canvas,
    Rect chartRect,
    _ChartTransform transform,
    _YAxisRange visibleYRange,
  ) {
    // Y-axis grid lines (based on the tick interval of the visible range)
    final tickCount =
        ((visibleYRange.max - visibleYRange.min) / visibleYRange.interval)
            .ceil() +
        1;

    for (int i = 0; i < tickCount; i++) {
      final value = visibleYRange.min + i * visibleYRange.interval;
      final y = transform.yToScreen(value);
      if (y >= chartRect.top && y <= chartRect.bottom) {
        canvas.drawLine(
          Offset(chartRect.left, y),
          Offset(chartRect.right, y),
          _gridPaint,
        );
      }
    }
  }

  /// Draws a data series.
  ///
  /// Before display, a "median + deadband" spike filter is applied in screen
  /// coordinates (drawing only — does not modify the RxList or CSV): isolated
  /// spikes (e.g. from motion on ACC, or transient hardware quantization noise
  /// on PPG) are smoothed out, while natural micro-jitter at rest (1-5 px in
  /// screen y) is preserved as-is.
  ///
  /// Filtering is skipped when:
  /// - [ChartDataSeries.showDots] = true: discrete points such as temperature,
  ///   where every point must be preserved exactly
  /// - fewer than 3 data points: a 3-point window cannot be formed
  void _drawSeries(
    Canvas canvas,
    ChartDataSeries seriesItem,
    _ChartTransform transform,
  ) {
    if (seriesItem.data.isEmpty) return;

    // Filter visible data points
    // Use < instead of <=, and add a small tolerance to avoid boundary-point flicker
    final visibleData = seriesItem.data.where((spot) {
      return currentTime - spot.x < windowSeconds + 0.1;
    }).toList();

    if (visibleData.isEmpty) return;

    // Convert to screen coordinates
    var points = visibleData.map((spot) {
      return transform.dataToScreen(spot);
    }).toList();

    if (points.isEmpty) return;

    // Screen-level "median + deadband" spike filter (display only — not written back to series.data, CSV unchanged)
    if (!seriesItem.showDots && points.length >= 3) {
      points = _despikeScreenPoints(points);
    }

    // Draw the polyline
    final path = Path();
    final linePaint = Paint()
      ..color = seriesItem.color
      ..strokeWidth = seriesItem.strokeWidth
      ..style = PaintingStyle.stroke
      ..strokeCap = StrokeCap.round;

    path.moveTo(points.first.dx, points.first.dy);
    for (final point in points.skip(1)) {
      path.lineTo(point.dx, point.dy);
    }

    canvas.drawPath(path, linePaint);

    // Optional: draw point markers
    if (seriesItem.showDots) {
      final dotPaint = Paint()
        ..color = seriesItem.color
        ..style = PaintingStyle.fill;

      for (final point in points) {
        canvas.drawCircle(point, 2.0, dotPaint);
      }
    }
  }

  /// Screen-level "median + deadband" spike filter (only replaces the screen y
  /// of anomalous isolated points, preserving x).
  ///
  /// Criteria (for each interior point i):
  /// 1. Compute the 3-point screen-y median `medY = median3(yPrev, yCur, yNext)`
  /// 2. Deviation `|yCur − medY|`
  /// 3. Replace yCur with medY only if the deviation > [_kDeadbandPx] (= 5
  ///    pixels); otherwise keep yCur
  ///
  /// This is "median filtering + deadband", the standard de-glitching approach
  /// used by professional instruments:
  /// - At rest, screen y jitters 1-5 px and the median differs from the
  ///   original by ≤ 5, so **no replacement → the original waveform is 100%
  ///   preserved, avoiding flat segments from repeated identical y values**
  /// - Isolated spikes during motion deviate 9+ px from the median, well beyond
  ///   the deadband → replaced with the median → smoothed
  /// - Normal transition points during motion (monotonic rise/fall) are the
  ///   median themselves, so deviation = 0 → no replacement
  ///
  /// Complexity O(N), a constant number of float comparisons per point, < 5μs
  /// per frame.
  static const double _kDeadbandPx = 5.0;

  List<Offset> _despikeScreenPoints(List<Offset> pts) {
    final n = pts.length;
    final out = List<Offset>.from(pts);
    for (var i = 1; i < n - 1; i++) {
      final yPrev = pts[i - 1].dy;
      final yCur = pts[i].dy;
      final yNext = pts[i + 1].dy;
      // 3-point median: max(min(a,b), min(max(a,b), c))
      final medY = (yPrev > yCur)
          ? ((yCur > yNext) ? yCur : (yPrev > yNext ? yNext : yPrev))
          : ((yPrev > yNext) ? yPrev : (yCur > yNext ? yNext : yCur));
      if ((yCur - medY).abs() > _kDeadbandPx) {
        out[i] = Offset(pts[i].dx, medY);
      }
    }
    return out;
  }

  /// Draws the X axis (fixed positions, dynamic time labels).
  void _drawXAxis(Canvas canvas, Rect chartRect) {
    // Fixed 7 tick positions: 0%, 16.67%, 33.33%, 50%, 66.67%, 83.33%, 100%
    final positions = [0.0, 1 / 6, 2 / 6, 0.5, 4 / 6, 5 / 6, 1.0];

    // Determine the current mode
    final isScrollMode = currentTime >= windowSeconds;

    // Compute the time range currently displayed
    final actualDisplayWindow = isScrollMode ? windowSeconds : currentTime;

    // Compute the current latest time (based on currentTime)
    // referenceTime is usually UTC and needs to be converted to local time
    final now = referenceTime?.toLocal() ?? DateTime.now();
    final latestTime = now.add(
      Duration(milliseconds: (currentTime * 1000).toInt()),
    );

    for (final ratio in positions) {
      final x = chartRect.left + ratio * chartRect.width;

      // Draw the tick line
      canvas.drawLine(
        Offset(x, chartRect.bottom),
        Offset(x, chartRect.bottom + 5),
        Paint()
          ..color = Colors.grey.shade400
          ..strokeWidth = 1.r,
      );

      // Compute the label time
      final DateTime labelTime;

      if (isScrollMode) {
        // Scroll mode: ratio = 0.0 (left) → oldest time, ratio = 1.0 (right) → latest time
        final offsetSeconds = (1.0 - ratio) * windowSeconds;
        labelTime = latestTime.subtract(
          Duration(milliseconds: (offsetSeconds * 1000).toInt()),
        );
      } else {
        // Stretch mode: ratio = 0.0 (left) → start time, ratio = 1.0 (right) → current latest time
        // Labels are based on the actual display range (actualDisplayWindow) rather than windowSeconds
        final timeAtRatio = ratio * actualDisplayWindow;
        labelTime = now.add(
          Duration(milliseconds: (timeAtRatio * 1000).toInt()),
        );
      }

      // Format the label
      final label = DateFormat('HH:mm:ss').format(labelTime);

      // Draw the label text (boundary ticks use special alignment to avoid truncation)
      TextAlign align;
      double textX = x;
      final labelPadding = -2.w; // Distance of boundary ticks from the edge

      if (ratio == 0.0) {
        // Leftmost: left-aligned, offset right
        align = TextAlign.left;
        textX = x + labelPadding;
      } else if (ratio == 1.0) {
        // Rightmost: right-aligned, offset left
        align = TextAlign.right;
        textX = x - labelPadding;
      } else {
        // Middle ticks: center-aligned
        align = TextAlign.center;
      }

      _drawText(canvas, label, Offset(textX, chartRect.bottom + 12.h), align);
    }
  }

  /// Draws the Y axis.
  void _drawYAxis(Canvas canvas, Rect chartRect, _YAxisRange visibleYRange) {
    // Draw tick lines and labels (using the visible range)
    final tickCount =
        ((visibleYRange.max - visibleYRange.min) / visibleYRange.interval)
            .ceil() +
        1;

    // Create a temporary transform to compute Y coordinates
    final baseYRange = _calculateYRange();
    final transform = _ChartTransform(
      chartRect: chartRect,
      windowSeconds: windowSeconds,
      currentTime: currentTime,
      minY: baseYRange.min,
      maxY: baseYRange.max,
      yZoomScale: yZoomScale,
      viewportCenter: viewportCenter,
      minDataTime: _getMinDataTimeFromSeries(series),
    );

    for (int i = 0; i < tickCount; i++) {
      final value = visibleYRange.min + i * visibleYRange.interval;
      final y = transform.yToScreen(value);

      // Only draw labels within the chart range (relaxed so boundary labels stay visible)
      if (y < chartRect.top - 5 || y > chartRect.bottom + 5) continue;

      // Draw the tick line
      canvas.drawLine(
        Offset(chartRect.left - 5, y),
        Offset(chartRect.left, y),
        Paint()
          ..color = Colors.grey.shade400
          ..strokeWidth = 1.0,
      );

      // Draw the label text
      final label = _formatYValue(value, visibleYRange.interval);
      _drawText(canvas, label, Offset(chartRect.left - 6, y), TextAlign.right);
    }
  }

  /// Draws the border.
  void _drawBorder(Canvas canvas, Rect chartRect) {
    final borderPaint = Paint()
      ..color = Colors.grey.shade200
      ..strokeWidth = 1.0
      ..style = PaintingStyle.stroke;

    // Axis extension length (the part beyond the tick lines, for a nicer look)
    const axisExtension = 4.0;

    // Draw the top and right borders (regular color)
    canvas.drawLine(
      Offset(chartRect.left, chartRect.top),
      Offset(chartRect.right, chartRect.top),
      borderPaint,
    );
    canvas.drawLine(
      Offset(chartRect.right, chartRect.top),
      Offset(chartRect.right, chartRect.bottom),
      borderPaint,
    );

    // Draw the left Y axis (darker color, extended upward)
    canvas.drawLine(
      Offset(chartRect.left, chartRect.top - axisExtension),
      Offset(chartRect.left, chartRect.bottom),
      _axisPaint,
    );

    // Draw the bottom X axis (darker color, extended to the right)
    canvas.drawLine(
      Offset(chartRect.left, chartRect.bottom),
      Offset(chartRect.right + axisExtension, chartRect.bottom),
      _axisPaint,
    );
  }

  /// Draws the touch highlight (enlarged dot).
  void _drawTouchedPointHighlight(
    Canvas canvas,
    _TouchedDataPoint touched,
    _ChartTransform transform,
  ) {
    // Recompute the current screen coordinates (the data may have scrolled)
    final currentScreenPosition = transform.dataToScreen(touched.dataPoint);

    // Draw the enlarged dot (outer ring - semi-transparent)
    final outerDotPaint = Paint()
      ..color = touched.color.withValues(alpha: 0.3)
      ..style = PaintingStyle.fill;

    canvas.drawCircle(currentScreenPosition, 8.0, outerDotPaint);

    // Draw the enlarged dot (inner ring - solid)
    final innerDotPaint = Paint()
      ..color = touched.color
      ..style = PaintingStyle.fill;

    canvas.drawCircle(currentScreenPosition, 5.0, innerDotPaint);

    // Draw the white border
    final borderPaint = Paint()
      ..color = Colors.white
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2.0;

    canvas.drawCircle(currentScreenPosition, 5.0, borderPaint);
  }

  /// Draws text.
  void _drawText(Canvas canvas, String text, Offset offset, TextAlign align) {
    final paragraphBuilder =
        ui.ParagraphBuilder(
            ui.ParagraphStyle(textAlign: align, fontFamily: 'Roboto'),
          )
          ..pushStyle(ui.TextStyle(color: Color(0xFF9E9E9E), fontSize: 9.sp))
          ..addText(text)
          ..pop();

    final paragraph = paragraphBuilder.build()
      ..layout(ui.ParagraphConstraints(width: 50.w));

    // Adjust the position based on the alignment
    double dx = offset.dx;
    if (align == TextAlign.center) {
      dx -= paragraph.width / 2;
    } else if (align == TextAlign.right) {
      dx -= paragraph.width;
    }

    canvas.drawParagraph(
      paragraph,
      Offset(dx, offset.dy - paragraph.height / 2),
    );
  }

  /// Formats a Y-axis value.
  String _formatYValue(double value, double interval) {
    // Decide the number of decimal places based on the interval size
    int decimalDigits;
    if (interval >= 1000) {
      decimalDigits = 0;
    } else if (interval >= 100) {
      decimalDigits = 0;
    } else if (interval >= 10) {
      decimalDigits = 0;
    } else if (interval >= 1) {
      decimalDigits = 0;
    } else if (interval >= 0.1) {
      decimalDigits = 1;
    } else if (interval >= 0.01) {
      decimalDigits = 2;
    } else {
      decimalDigits = 3;
    }

    final absValue = value.abs();

    // Use k/M to simplify the display of large values
    if (absValue >= 1000000) {
      return '${(value / 1000000).toStringAsFixed(1)}M';
    } else if (absValue >= 1000) {
      return '${(value / 1000).toStringAsFixed(1)}k';
    }

    // Display small values directly with an appropriate number of decimals
    return value.toStringAsFixed(decimalDigits);
  }

  @override
  bool shouldRepaint(_RealTimeChartPainter oldDelegate) {
    return oldDelegate.series != series ||
        oldDelegate.currentTime != currentTime ||
        oldDelegate.yZoomScale != yZoomScale ||
        oldDelegate.viewportCenter != viewportCenter ||
        oldDelegate.referenceTime != referenceTime ||
        oldDelegate.touchedDataPoint != touchedDataPoint; // Repaint when the touch state changes
  }
}

/// Coordinate transformer.
///
/// Handles the conversion from data space to screen space.
class _ChartTransform {
  final Rect chartRect;
  final double windowSeconds;
  final double currentTime;
  final double minY;
  final double maxY;
  final double yZoomScale;
  final double viewportCenter;
  final double minDataTime; // The time of the earliest data point

  _ChartTransform({
    required this.chartRect,
    required this.windowSeconds,
    required this.currentTime,
    required this.minY,
    required this.maxY,
    required this.yZoomScale,
    required this.viewportCenter,
    required this.minDataTime,
  });

  /// Whether there is enough data to fill the window (scroll mode).
  bool get isScrollMode => currentTime >= windowSeconds;

  /// The time range currently displayed (< windowSeconds in stretch mode).
  double get actualDisplayWindow => isScrollMode ? windowSeconds : currentTime;

  /// Converts a data point to screen coordinates.
  Offset dataToScreen(DataPoint spot) {
    final double x;

    if (isScrollMode) {
      // Scroll mode: fixed time window, new data on the right
      final timeDelta = currentTime - spot.x;
      final xRatio = timeDelta / windowSeconds; // 0.0 = latest, 1.0 = oldest
      x = chartRect.right - xRatio * chartRect.width;
    } else {
      // Stretch mode: data fills the entire chart width from left to right
      // Normalize the data point's time relative to the earliest data point
      // The earliest data point (spot.x = minDataTime) is at the far left
      // The latest data point (spot.x = currentTime) is at the far right
      final timeSpan = currentTime - minDataTime;
      final xRatio = timeSpan > 0 ? (spot.x - minDataTime) / timeSpan : 0.0;
      x = chartRect.left + xRatio * chartRect.width;
    }

    // Y axis: account for zoom and viewport center
    final yRange = maxY - minY;
    final normalizedY = (spot.y - minY) / yRange; // 0.0 - 1.0

    // Compute the offset relative to the viewport center
    final offsetFromCenter = (normalizedY - viewportCenter) * yZoomScale;
    // Map to screen coordinates (0.5 is the screen center)
    final screenY = 0.5 + offsetFromCenter;

    final y = chartRect.bottom - screenY * chartRect.height;

    return Offset(x, y);
  }

  /// Converts a Y-axis value to a screen Y coordinate.
  double yToScreen(double value) {
    final yRange = maxY - minY;
    final normalizedY = (value - minY) / yRange;
    final offsetFromCenter = (normalizedY - viewportCenter) * yZoomScale;
    final screenY = 0.5 + offsetFromCenter;
    return chartRect.bottom - screenY * chartRect.height;
  }
}

/// Y-axis range.
class _YAxisRange {
  final double min;
  final double max;
  final double interval;

  _YAxisRange({required this.min, required this.max, required this.interval});
}

/// Empty chart placeholder.
class _EmptyChart extends StatelessWidget {
  const _EmptyChart();

  @override
  Widget build(BuildContext context) {
    return Container(
      alignment: Alignment.center,
      decoration: BoxDecoration(
        border: Border.all(color: Colors.grey.shade200),
        borderRadius: BorderRadius.circular(8.r),
        color: Colors.grey.shade50,
      ),
      child: const Text('No data', style: TextStyle(color: Colors.black45)),
    );
  }
}

/// Information about the touched data point.
class _TouchedDataPoint {
  final DataPoint dataPoint;
  final Offset screenPosition;
  final int seriesIndex;
  final Color color;
  final String? seriesName;

  _TouchedDataPoint({
    required this.dataPoint,
    required this.screenPosition,
    required this.seriesIndex,
    required this.color,
    this.seriesName,
  });
}
