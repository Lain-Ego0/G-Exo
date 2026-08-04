import 'package:flutter/material.dart';
import 'package:flutter_screenutil/flutter_screenutil.dart';

/// Common title text widget
class CommonTitleText extends StatelessWidget {
  final String title;

  final TextStyle? style;

  /// Default text style
  final TextStyle defaultStyle = TextStyle(fontSize: 20.sp);

   CommonTitleText({super.key, required this.title, this.style});

  @override
  Widget build(BuildContext context) {
    return Text(title, style: style ?? defaultStyle);
  }
}
