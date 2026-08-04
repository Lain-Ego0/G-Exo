import 'package:flutter/material.dart';

import 'package:alloop_blue_lite/alloop_blue_lite.dart';

void main() {
  runApp(const MyApp());
}

class MyApp extends StatelessWidget {
  const MyApp({super.key});

  @override
  Widget build(BuildContext context) {
    AlloopBlueLite.instance;
    return MaterialApp(
      home: Scaffold(
        appBar: AppBar(
          title: const Text('Plugin example app'),
        ),
        body: const Center(
          child: Text('alloop_blue_lite scaffold'),
        ),
      ),
    );
  }
}
