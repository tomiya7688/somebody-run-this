import 'package:flutter/widgets.dart';

import 'application/user_service.dart';
import 'frontends/jp_soft_pop/app.dart';
import 'infrastructure/http_user_gateway.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();

  const serverUrl = String.fromEnvironment(
    'FX_CHANNEL_SERVER_URL',
    defaultValue: '',
  );
  const frontend = String.fromEnvironment(
    'FX_CHANNEL_USER_FRONTEND',
    defaultValue: 'jp_soft_pop',
  );

  final service = UserService(
    HttpUserGateway(baseUrl: serverUrl),
  );

  switch (frontend) {
    case 'jp_soft_pop':
      runApp(JpSoftPopApp(service: service));
      return;
    default:
      throw StateError('Unknown user frontend: $frontend');
  }
}
