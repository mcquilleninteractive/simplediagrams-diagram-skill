// Opens documents exactly as SimpleDiagrams for Mac does and prints what it makes of each, as
// one JSON object a line, for check_against_app.py. It is compiled against the app's own
// reader from a copy of the app's source; it is never part of the skill an agent runs.

import Foundation
import SimpleDiagramsCore

struct Report: Encodable {
  let path: String
  let error: String?
  /// The connection points of every complex shape, by element id then point number, as
  /// fractions of its frame: those the app worked out as it read the document.
  let points: [String: [String: [Double]]]
}

let encoder = JSONEncoder()
for path in CommandLine.arguments.dropFirst() {
  var error: String?
  var points: [String: [String: [Double]]] = [:]
  do {
    let contents = try ModernDiagramPackageCodec.decode(contentsOf: URL(fileURLWithPath: path))
    for page in contents.snapshot.pages {
      for element in page.elements where element.complexShape != nil {
        points[element.id.uuidString] = Dictionary(
          uniqueKeysWithValues: element.connectionPoints.map {
            (String($0.id), [$0.position.x, $0.position.y])
          })
      }
    }
  } catch let failure {
    error = (failure as? LocalizedError)?.errorDescription ?? String(describing: failure)
  }
  let line = try encoder.encode(Report(path: path, error: error, points: points))
  print(String(decoding: line, as: UTF8.self))
}
